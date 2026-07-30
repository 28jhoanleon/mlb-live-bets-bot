"""Arma el estado de las apuestas para la web.

Reusa exactamente la misma lógica que el bot de Telegram (tickets,
tracking en vivo, probabilidad). La única diferencia es la salida: acá
devolvemos datos crudos en JSON y el navegador se encarga de dibujar,
en vez de armar texto con emojis.

Es el punto de la arquitectura: una sola fuente de verdad, dos formas
de mostrarla.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
from typing import Any

from app.analysis.live_tracking import get_live_tracking_for_match, track_leg_live
from app.analysis.probability import ProbabilityError, estimate_leg_detail, estimate_leg_probability
from app.analysis.tickets import normalize
from app.db.database import get_active_bet, marcar_terminado_si_hace_falta, olvidar_terminado
from app.mlb.estados import CON_DATOS as _CON_DATOS
from app.mlb.estados import TERMINADO as _TERMINADO
from app.mlb.schedule import buscar_partido
from app.utils.equipos import logo_equipo, nombre_corto, partido_corto
from app.utils.logger import get_logger
from app.utils.market_labels import nombre_stake
from app.utils.progress_bar import target_needed
from app.utils.tiempo import formato_hora_fecha

log = get_logger(__name__)

# Cuánto se muestra un ticket DESPUÉS de que todos sus partidos terminaron
# antes de sacarlo de la lista por completo. Da tiempo a revisar cómo
# quedó sin acumular tickets viejos para siempre.
TOLERANCIA_TICKET_TERMINADO = timedelta(hours=3)


def _equipos_de(match: str) -> tuple[str, str]:
    for sep in (" @ ", " vs ", " - "):
        if sep in match:
            a, b = match.split(sep, 1)
            return a.strip(), b.strip()
    return match.strip(), ""


def _estado_leg(status) -> str:
    """Traduce el estado interno a una clase que la web entiende."""
    # El orden importa: una leg de un partido TERMINADO que no se cumplió
    # está perdida, no "en curso".
    if getattr(status, "perdida", False):
        return "lost"
    if status.already_hit:
        return "done"
    if "🔴" in status.active_status:
        return "dead"
    return "live"


def _pct(actual: float, objetivo: float, cumplida: bool) -> float:
    if cumplida:
        return 100.0
    if objetivo <= 0:
        return 0.0
    return round(max(0.0, min(actual / objetivo, 1.0)) * 100, 1)


def _leg_en_vivo(leg: dict, boxscore: dict, live_state: dict) -> dict[str, Any] | None:
    try:
        status = track_leg_live(leg, boxscore, live_state)
    except ProbabilityError as e:
        if "en el boxscore de este partido" in str(e):
            # El partido SÍ está en vivo y tenemos el roster completo de los
            # dos equipos, pero este jugador no aparece en ninguno. Casi
            # siempre es un nombre mal leído por la IA de la captura (un
            # jugador real, pero de otro equipo) -- no de verdad "no hay
            # datos". Avisamos en vez de mostrar tranquilamente el
            # promedio histórico de otra persona.
            return {
                "player": leg.get("player") or "Sin jugador",
                "market": nombre_stake(leg.get("market", "")) or leg.get("market", ""),
                "line": leg.get("line", ""),
                "odds": leg.get("odds"),
                "current": 0,
                "goal": 0,
                "pct": 0,
                "state": "warn",
                "note": "No lo encuentro en el roster de este partido — revisá el nombre en la captura",
                "live": True,
            }
        return None

    objetivo = target_needed(status.threshold, status.side)
    estado = _estado_leg(status)
    # En una leg ya cumplida, el tilde verde y la barra llena ya dicen
    # todo: repetirlo con "ASEGURADA — ya no puede revertirse" es ruido.
    nota = "" if estado == "done" else status.status_text
    return {
        "player": status.player,
        "market": nombre_stake(leg.get("market", "")) or leg.get("market", ""),
        "line": leg.get("line", ""),
        "odds": leg.get("odds"),
        "current": status.current_value,
        "goal": objetivo,
        "pct": _pct(status.current_value, objetivo, status.already_hit),
        "state": estado,
        "note": nota,
        "player_status": status.active_status,
        "live": True,
    }


def _leg_historica(leg: dict) -> dict[str, Any]:
    """Sin partido en vivo mostramos la forma reciente: en cuántos de sus
    últimos partidos superó esa línea."""
    base = {
        "player": leg.get("player") or "Sin jugador",
        "market": nombre_stake(leg.get("market", "")) or leg.get("market", ""),
        "line": leg.get("line", ""),
        "odds": leg.get("odds"),
        "live": False,
    }
    try:
        est = estimate_leg_probability(
            leg.get("player", ""), leg.get("market", ""), leg.get("line", "")
        )
    except (ProbabilityError, Exception):
        return {**base, "state": "unknown", "pct": 0, "note": "Sin datos suficientes"}

    cumplidos = round(est.probability_pct / 100 * est.sample_size)
    return {
        **base,
        "player": est.player,
        "current": cumplidos,
        "goal": est.sample_size,
        "pct": _pct(cumplidos, est.sample_size, False),
        "state": "good" if est.probability_pct >= 60 else ("mid" if est.probability_pct >= 35 else "bad"),
        "note": f"{est.probability_pct}% en sus últimos {est.sample_size} · promedio {est.avg_value}",
    }


def _datos_del_partido(
    match_text: str, match_datetime: str | None = None
) -> tuple[dict | None, tuple | None]:
    """Devuelve (entrada del calendario, datos en vivo) para un partido.

    match_datetime es la fecha del partido leída de la captura. Es lo
    único que distingue dos partidos del MISMO cruce en días seguidos
    -- sin eso, un ticket de ayer se engancha al partido de hoy."""
    partido = None
    try:
        a, h = _equipos_de(match_text)
        partido = buscar_partido(a, h, match_datetime)
    except Exception:
        log.exception("Error buscando el partido en el calendario")

    live_data = None
    if partido and partido.get("status") in _CON_DATOS:
        try:
            live_data = get_live_tracking_for_match(match_text, match_datetime)
        except Exception:
            log.exception("Error trayendo el estado en vivo")
    return partido, live_data


def _armar_grupo(match_text: str, legs_raw: list[dict]) -> dict[str, Any]:
    """Un grupo = las legs de UN partido dentro de una apuesta.

    Cada grupo busca su propio partido. Antes se buscaba uno solo por
    apuesta y se aplicaba a todas las legs: en una combinada de varios
    juegos, las selecciones de los otros partidos nunca recibían datos en
    vivo y se quedaban mostrando el promedio histórico.
    """
    # Todas las legs de un grupo son del mismo partido: alcanza con la
    # fecha de la primera que la tenga.
    match_datetime = next(
        (l.get("match_datetime") for l in legs_raw if l.get("match_datetime")), None
    )
    partido, live_data = _datos_del_partido(match_text, match_datetime)

    def _procesar_leg(leg: dict) -> dict[str, Any]:
        resultado = None
        if live_data:
            boxscore, live_state = live_data
            resultado = _leg_en_vivo(leg, boxscore, live_state)
        return resultado or _leg_historica(leg)

    # Las legs en vivo no pegan a la red (ya tenemos boxscore/live_state
    # del grupo). Las que caen al histórico sí -2 llamadas cada una-, y
    # antes se hacían una por una: una combinada con varias legs sin
    # partido arrancado tardaba la suma de todas. En paralelo tarda lo
    # que tarda la más lenta.
    if len(legs_raw) > 1:
        with ThreadPoolExecutor(max_workers=min(8, len(legs_raw))) as ex:
            legs = list(ex.map(_procesar_leg, legs_raw))
    else:
        legs = [_procesar_leg(leg) for leg in legs_raw]

    if partido:
        away_nombre = partido.get("away_team")
        home_nombre = partido.get("home_team")
    else:
        away_nombre, home_nombre = _equipos_de(match_text)

    grupo: dict[str, Any] = {
        "match": partido_corto(match_text),
        "away": nombre_corto(away_nombre),
        "home": nombre_corto(home_nombre),
        "away_logo": logo_equipo(away_nombre),
        "home_logo": logo_equipo(home_nombre),
        "start": formato_hora_fecha(partido.get("game_time_utc")) if partido else None,
        "status": partido.get("status") if partido else None,
        "terminado": bool(partido and partido.get("status") in _TERMINADO),
        "odds": (legs_raw[0].get("group_odds") if legs_raw else None),
        "legs": legs,
        "done": sum(1 for l in legs if l.get("state") == "done"),
        "total": len(legs),
        "live": bool(live_data),
    }

    if live_data:
        _, live_state = live_data
        traducido = {
            "Top": "arriba", "Bottom": "abajo",
            "Middle": "medio", "End": "fin",
        }.get(live_state.get("inning_state") or "", "")
        grupo.update({
            "inning": live_state.get("inning"),
            "inning_state": traducido,
            "away_score": live_state.get("away_score"),
            "home_score": live_state.get("home_score"),
        })

    return grupo


def _ticket_id(ticket: dict, legs_raw: list[dict]) -> str:
    """Id estable de un ticket, a partir de lo que NO cambia con el
    tiempo (label, cuota total, y qué legs son). El estado en vivo sí
    cambia en cada refresco, por eso no puede ser parte del id."""
    piezas = "|".join(sorted(
        f"{l.get('match', '')}~{str(l.get('match_datetime') or '')[:10]}~"
        f"{l.get('player', '')}~{l.get('market', '')}~{l.get('line', '')}"
        for l in legs_raw
    ))
    crudo = f"{ticket.get('label') or ''}::{ticket.get('total_odds') or ''}::{piezas}"
    return hashlib.sha1(crudo.encode("utf-8")).hexdigest()[:16]


def estado_apuestas(chat_id: int) -> dict[str, Any]:
    """Devuelve las apuestas guardadas, cada una dividida en grupos por
    partido — igual que las muestra la casa de apuestas."""
    guardado = get_active_bet(chat_id)
    tickets = normalize(guardado or {})

    salida: list[dict[str, Any]] = []

    for ticket in tickets:
        legs_raw = ticket.get("legs", [])
        if not legs_raw:
            continue

        # Agrupamos por partido conservando el orden de aparición
        # La clave incluye la FECHA: los mismos dos equipos pueden jugar
        # dos días seguidos, y ésos son dos partidos distintos, no uno.
        por_partido: dict[tuple[str, str], list[dict]] = {}
        for leg in legs_raw:
            nombre = (leg.get("match") or ticket.get("match") or "").strip()
            dia = str(leg.get("match_datetime") or "")[:10]
            por_partido.setdefault((nombre, dia), []).append(leg)

        items = [(nombre, ls) for (nombre, _dia), ls in por_partido.items()]
        if len(items) > 1:
            with ThreadPoolExecutor(max_workers=min(8, len(items))) as ex:
                grupos = list(ex.map(lambda kv: _armar_grupo(*kv), items))
        else:
            grupos = [_armar_grupo(m, ls) for m, ls in items]

        cumplidas = sum(g["done"] for g in grupos)
        total = sum(g["total"] for g in grupos)

        terminado = bool(grupos) and all(g["terminado"] for g in grupos)
        ticket_id = _ticket_id(ticket, legs_raw)

        if terminado:
            desde_iso = marcar_terminado_si_hace_falta(chat_id, ticket_id)
            desde = datetime.fromisoformat(desde_iso)
            if desde.tzinfo is None:
                desde = desde.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) - desde > TOLERANCIA_TICKET_TERMINADO:
                continue  # ya pasó la tolerancia: se saca de la lista del todo
        else:
            olvidar_terminado(chat_id, ticket_id)

        salida.append({
            "label": ticket.get("label"),
            "odds": ticket.get("total_odds"),
            "declaradas": ticket.get("legs_declaradas"),
            "grupos": grupos,
            "done": cumplidas,
            "total": total,
            "live": any(g["live"] for g in grupos),
            "terminado": terminado,
        })

    return {"tickets": salida, "count": len(salida)}


def detalle_leg(player: str, market: str, line: str) -> dict[str, Any]:
    """Desglose partido-por-partido de una leg puntual. Es lo que pide
    el botón de 'profundizar' en cada leg: no el resumen ('90% en sus
    últimos 10'), sino el detalle de cada uno de esos partidos."""
    detalle = estimate_leg_detail(player, market, line)
    return {
        "player": detalle.player,
        "market": nombre_stake(market) or market,
        "side": detalle.side,
        "threshold": detalle.threshold,
        "probability_pct": detalle.probability_pct,
        "avg_value": detalle.avg_value,
        "games": [
            {"date": g.date, "value": g.value, "hit": g.hit} for g in detalle.games
        ],
    }
