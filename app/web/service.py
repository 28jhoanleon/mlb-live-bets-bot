"""Arma el estado de las apuestas para la web.

Reusa exactamente la misma lógica que el bot de Telegram (tickets,
tracking en vivo, probabilidad). La única diferencia es la salida: acá
devolvemos datos crudos en JSON y el navegador se encarga de dibujar,
en vez de armar texto con emojis.

Es el punto de la arquitectura: una sola fuente de verdad, dos formas
de mostrarla.
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
from typing import Any

from app.analysis.live_tracking import get_live_tracking_for_match, track_leg_live
from app.analysis.probability import (
    precalentar_cache,
    ProbabilityError,
    estimate_leg_detail,
    estimate_leg_probability,
    estimate_team_detail,
    estimate_team_probability,
    mejor_alternativa,
    sugerir_lineas,
)
from app.analysis.tickets import normalize
from app.analysis.turnos import describir_turnos, turnos_restantes
from app.db.database import (
    get_active_bet,
    marcar_terminado_si_hace_falta,
    olvidar_terminado,
    registrar_legs_resueltas,
)
from app.mlb.estados import CON_DATOS as _CON_DATOS
from app.mlb.estados import EN_CURSO as _EN_CURSO
from app.mlb.estados import POR_EMPEZAR as _POR_EMPEZAR
from app.mlb.estados import TERMINADO as _TERMINADO
from app.mlb.players import get_hitting_split_vs_hand, get_season_hitting_stats, search_player
from app.analysis.probability import LegEstimate
from app.mlb.schedule import buscar_partido
from app.utils.equipos import equipos_en_texto, logo_equipo, nombre_corto, partido_corto
from app.utils.logger import get_logger
from app.utils.market_labels import nombre_stake_texto
from app.utils.progress_bar import target_needed
from app.utils.tiempo import formato_hora_fecha

log = get_logger(__name__)

# Cuánto se muestra un ticket DESPUÉS de que todos sus partidos terminaron
# antes de sacarlo de la lista por completo. Da tiempo a revisar cómo
# quedó sin acumular tickets viejos para siempre.
TOLERANCIA_TICKET_TERMINADO = timedelta(hours=3)


def _partido_del_jugador(nombre: str) -> str | None:
    """Deduce el partido a partir del jugador.

    Hace falta porque algunos cupones de Stake listan solo el escudo del
    equipo, sin el nombre del cruce. La IA no puede leer un logo, así que
    la leg llega sin partido y en la web aparecía "? @ ?" sin datos en
    vivo. Sabiendo de qué equipo es el jugador, el calendario de hoy dice
    contra quién juega.
    """
    from app.mlb.players import search_player
    from app.mlb.schedule import get_schedule_cacheado

    try:
        datos = search_player(nombre)
    except Exception:
        return None
    equipo = (datos or {}).get("team")
    if not equipo:
        return None

    # Comparación tolerante: la MLB API puede devolver el equipo con
    # cualquier variante ("Red Sox", "Boston Red Sox"). Comparar el texto
    # exacto hacía que la deducción fallara casi siempre y todas las legs
    # terminaran agrupadas bajo un mismo "? @ ?".
    from app.utils.equipos import id_equipo

    id_buscado = id_equipo(equipo)
    bajo = equipo.lower()
    from datetime import timedelta

    from app.utils.tiempo import hoy_local

    # SOLO hoy, y ayer como respaldo. Las apuestas siempre son del día;
    # mirar "mañana" solo agregaba chances de agarrar el partido
    # equivocado cuando los mismos equipos juegan una serie. Ayer se
    # conserva porque un partido nocturno sigue vivo pasada la medianoche.
    try:
        for offset in (0, -1):
            dia = hoy_local() + timedelta(days=offset)
            for juego in get_schedule_cacheado(dia):
                away = (juego.get("away_team") or "")
                home = (juego.get("home_team") or "")
                if id_buscado and id_buscado in (id_equipo(away), id_equipo(home)):
                    return f"{away} @ {home}"
                if bajo and bajo in (away.lower(), home.lower()):
                    return f"{away} @ {home}"
    except Exception:
        log.debug("No pude deducir el partido de %s", nombre, exc_info=True)
    return None


def _equipos_de(match: str) -> tuple[str, str]:
    """Separa el cruce en (visitante, local).

    Primero se buscan equipos MLB conocidos dentro del texto: es lo único
    que aguanta las variantes que escribe la IA según la captura
    ("Dodgers @ Royals", "... vs. ...", "... - ..."). Partir por separador
    quedó como respaldo, porque con un separador inesperado devolvía UN
    solo texto gigante que no matcheaba ningún partido -- y el grupo se
    quedaba sin horario ni datos en vivo, como si el partido no existiera.
    """
    equipos = equipos_en_texto(match)
    if len(equipos) >= 2:
        return equipos[0], equipos[1]

    for sep in (" @ ", " vs. ", " vs ", " - ", " at "):
        if sep in match:
            a, b = match.split(sep, 1)
            return a.strip(), b.strip()

    if len(equipos) == 1:
        return equipos[0], ""
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


def _turnos_de(leg: dict, status, boxscore: dict, live_state: dict) -> str:
    """Cuántos turnos al bate le quedan al jugador.

    Es lo que convierte "necesita 1 hit" en información accionable: con
    3 turnos por delante la leg está viva, con medio turno en la novena
    está prácticamente liquidada.

    Solo aplica a bateadores con la leg sin cumplir todavía: para un
    pitcher los "turnos" no significan nada, y una leg ya asegurada no
    necesita más oportunidades."""
    if status.already_hit or getattr(status, "perdida", False):
        return ""

    datos = boxscore.get(status.player) or {}
    orden = datos.get("batting_order")
    if not orden or datos.get("is_current_pitcher"):
        return ""

    turnos = turnos_restantes(
        orden,
        live_state.get("inning"),
        live_state.get("inning_state"),
        es_equipo_visitante=(datos.get("team_side") == "away"),
        outs=live_state.get("outs"),
    )
    return describir_turnos(turnos)


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
                "market": nombre_stake_texto(leg.get("market", "")),
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
        "market": nombre_stake_texto(leg.get("market", ""), status.is_pitcher),
        "line": leg.get("line", ""),
        "odds": leg.get("odds"),
        "current": status.current_value,
        "goal": objetivo,
        "pct": _pct(status.current_value, objetivo, status.already_hit),
        "state": estado,
        "note": nota,
        "turnos": _turnos_de(leg, status, boxscore, live_state),
        "player_status": status.active_status,
        "live": True,
    }


def _es_de_equipo(leg: dict) -> bool:
    """Stake ofrece mercados de EQUIPO ("Equipo, bases por bolas") y de
    PARTIDO ("Partido, ponches") además de los de jugador. No tienen
    jugador asociado, así que no se pueden estimar con el historial de
    un jugador."""
    ambito = str(leg.get("ambito") or "").lower()
    if ambito in ("equipo", "partido"):
        return True
    # Respaldo para apuestas leídas antes de que la visión extrajera
    # "ambito": sin jugador no hay historial que consultar, así que es de
    # equipo o de partido igual.
    return not leg.get("player")


def _leg_de_equipo(leg: dict) -> dict[str, Any]:
    """Mercados sin jugador. Hay dos casos bien distintos:

    - EQUIPO ("Royals, bases por bolas Over 2.5"): se estima con el
      gameLog del equipo, igual que un jugador un nivel más arriba.
    - PARTIDO ("Partido, ponches Under 14.5"): son los dos equipos
      juntos y dependen de quiénes lancen ese día, así que el historial
      del partido no sirve. Se muestra sin estimación a propósito: mejor
      decir "no sé" que dar un número que suene preciso y no lo sea.
    """
    ambito = str(leg.get("ambito") or "").lower()
    equipo = leg.get("team")
    base = {
        "player": equipo or ("Todo el partido" if ambito == "partido" else "Apuesta de equipo"),
        "market": nombre_stake_texto(leg.get("market", "")),
        "line": leg.get("line", ""),
        "odds": leg.get("odds"),
        "current": 0,
        "goal": 0,
        "pct": 0,
        "state": "unknown",
        "live": False,
    }

    if ambito == "partido":
        return {**base, "note": "Mercado de partido — depende de los pitchers del día, no lo estimo"}

    if not equipo:
        # Las apuestas guardadas ANTES de que la visión extrajera "team"
        # no traen el equipo, y no hay forma de saber cuál de los dos del
        # partido es. Mostrar el equivocado sería peor que no mostrar
        # nada, así que se pide releer la captura.
        return {
            **base,
            "note": "Apuesta de equipo sin identificar — reenviá la captura para que la lea de nuevo",
        }

    try:
        est = estimate_team_probability(equipo, leg.get("market", ""), leg.get("line", ""))
    except ProbabilityError as e:
        return {**base, "state": "unknown", "note": str(e)}
    except Exception:
        log.exception("Error estimando mercado de equipo")
        return {**base, "state": "unknown", "note": "No pude traer las estadísticas del equipo"}

    cumplidos = round(est.probability_pct / 100 * est.sample_size)
    return {
        **base,
        "current": cumplidos,
        "goal": est.sample_size,
        "pct": _pct(cumplidos, est.sample_size, False),
        "state": "good" if est.probability_pct >= 60 else ("mid" if est.probability_pct >= 35 else "bad"),
        "note": (f"{est.probability_pct}% en sus últimos {est.sample_size} "
                 f"· promedio {est.avg_value}"),
    }


_NOMBRE_MANO = {"L": "zurdos", "R": "derechos"}


def _split_vs_pitcher_texto(leg: dict, est: LegEstimate) -> str:
    """Texto extra opcional: cómo batea el jugador de esta leg contra la
    mano del abridor rival. Es solo informativo -- nunca toca el % ni
    el promedio ya calculados. Cualquier fallo se traga en silencio: si
    no se puede armar, el mensaje de siempre sigue funcionando igual.

    Reutiliza el jugador que `estimate_leg_probability` ya resolvió (en
    vez de buscarlo de nuevo): la primera vez que agregué esto hacía una
    búsqueda redundante por leg y eso duplicaba llamadas a la MLB API
    sin necesidad -- el test de rendimiento en paralelo lo agarró.
    """
    if est.is_pitcher or not est.player_id:
        return ""
    try:
        a, h = _equipos_de(leg.get("match", "") or "")
        partido = buscar_partido(a, h, leg.get("match_datetime"))
        if not partido:
            return ""

        equipo_jugador = (est.team or "").lower()
        away = (partido.get("away_team") or "").lower()
        home = (partido.get("home_team") or "").lower()
        if equipo_jugador and equipo_jugador in away:
            pitcher_rival = partido.get("home_pitcher")
        elif equipo_jugador and equipo_jugador in home:
            pitcher_rival = partido.get("away_pitcher")
        else:
            return ""
        if not pitcher_rival:
            return ""

        info_pitcher = search_player(pitcher_rival)
        mano = info_pitcher.get("throws") if info_pitcher else None
        if mano not in ("L", "R"):
            return ""

        split = get_hitting_split_vs_hand(est.player_id, mano)
        if not split or split.get("avg") is None:
            return ""

        temporada = get_season_hitting_stats(est.player_id)
        if not temporada or temporada.get("avg") is None:
            return ""

        try:
            avg_split = float(split["avg"])
            avg_temporada = float(temporada["avg"])
        except (TypeError, ValueError):
            return ""

        diferencia = avg_split - avg_temporada
        # +/- 20 puntos de average (.020) es la diferencia minima que
        # vale la pena mencionar -- por debajo de eso es ruido de
        # muestra, no una tendencia real.
        if diferencia >= 0.020:
            veredicto = "le pega MEJOR de lo normal"
        elif diferencia <= -0.020:
            veredicto = "le cuesta MAS de lo normal"
        else:
            veredicto = "rinde parecido a su promedio"

        return (
            f" · Contra {_NOMBRE_MANO[mano]} este año {veredicto} "
            f"({split['avg']} vs. {temporada['avg']} en general)"
        )
    except Exception:
        log.debug("No pude armar el split vs pitcher para %s", leg.get("player"), exc_info=True)
        return ""


def _leg_historica(leg: dict) -> dict[str, Any]:
    """Sin partido en vivo mostramos la forma reciente: en cuántos de sus
    últimos partidos superó esa línea."""
    if _es_de_equipo(leg):
        return _leg_de_equipo(leg)
    base = {
        "player": leg.get("player") or "Sin jugador",
        "market": nombre_stake_texto(leg.get("market", "")),
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
        # Ahora que conocemos el rol, el nombre del mercado se puede
        # desambiguar bien (los "Strikeouts" de un pitcher y los de un
        # bateador son mercados distintos en Stake).
        "market": nombre_stake_texto(leg.get("market", ""), est.is_pitcher),
        "state": "good" if est.probability_pct >= 60 else ("mid" if est.probability_pct >= 35 else "bad"),
        "note": (
            f"{est.probability_pct}% en sus últimos {est.sample_size} · promedio {est.avg_value}"
            + _split_vs_pitcher_texto(leg, est)
        ),
        "sugerencia": est.sugerencia,
    }


# Último estado en vivo bueno de cada partido. La MLB Stats API falla de
# a ratos (vimos 403 intermitentes en producción), y sin esto una sola
# consulta fallida hacía que un partido EN CURSO mostrara de golpe el
# promedio histórico, como si no estuviera pasando nada. Con la copia
# reciente el bache se disimula y la vista no parpadea.
_ULTIMO_VIVO: dict[str, tuple[float, tuple]] = {}
_VIGENCIA_ULTIMO_VIVO = 300  # 5 minutos


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
        clave = f"{partido.get('game_pk')}"
        try:
            live_data = get_live_tracking_for_match(match_text, match_datetime)
            if live_data:
                _ULTIMO_VIVO[clave] = (time.monotonic(), live_data)
        except Exception:
            log.exception("Error trayendo el estado en vivo")

        if not live_data:
            # Reusar el último estado bueno antes de rendirse: es
            # preferible mostrar datos de hace un minuto que volver al
            # promedio histórico y hacer parecer que el partido terminó.
            guardado = _ULTIMO_VIVO.get(clave)
            if guardado and time.monotonic() - guardado[0] < _VIGENCIA_ULTIMO_VIVO:
                live_data = guardado[1]
                log.info("Usando el último estado en vivo conocido de %s", match_text)

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

    # ¿El partido está EN CURSO pero no pudimos traer sus datos? Hay que
    # decirlo: mostrar el histórico sin aclarar nada hace parecer que el
    # partido no empezó o ya terminó.
    en_curso_sin_datos = (
        not live_data
        and partido is not None
        and partido.get("status") in _EN_CURSO
    )

    def _procesar_leg(leg: dict) -> dict[str, Any]:
        resultado = None
        if live_data:
            boxscore, live_state = live_data
            resultado = _leg_en_vivo(leg, boxscore, live_state)
        if resultado:
            return resultado

        historica = _leg_historica(leg)
        if en_curso_sin_datos:
            historica["note"] = (
                "Sin conexión con el dato en vivo · muestro su forma reciente"
            )
        return historica

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
        # La MLB marca "Warmup" unos 20 minutos ANTES del primer
        # lanzamiento. No es en vivo, pero avisar que está por arrancar
        # sí sirve; antes se mostraba como si ya estuviera jugándose.
        "por_empezar": bool(partido and partido.get("status") in _POR_EMPEZAR),
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


def _registrar_para_calibracion(
    chat_id: int, ticket_id: str, grupos: list[dict], legs_raw: list[dict]
) -> None:
    """Guarda TODAS las legs del ticket recién terminado -acertadas y
    falladas- con la probabilidad que se había estimado antes de que se
    jugara. Es lo que después permite medir si el modelo está inflado.

    A propósito NO se filtra por "el ticket salió ganador": guardar solo
    los aciertos sería sesgo de supervivencia y no serviría para medir
    nada. Un jugador puede haber sido un pick excelente y estar en un
    ticket que se rompió por otro tramo."""
    # La leg mostrada trae el mercado ya traducido (nombre_stake), la
    # cruda no: hay que normalizar los dos lados o la clave no matchea.
    def _clave(jugador, mercado, linea):
        return (jugador, nombre_stake_texto(mercado or ""), linea)

    prob_por_leg = {
        _clave(l.get("player"), l.get("market"), l.get("line")): l.get("prob_estimada")
        for l in legs_raw
    }

    filas = []
    for grupo in grupos:
        for leg in grupo.get("legs", []):
            if leg.get("state") not in ("done", "lost"):
                continue  # sin resultado claro no aporta nada
            clave = (leg.get("player"), leg.get("market"), leg.get("line"))
            # leg["market"] ya viene traducido, así que no se vuelve a pasar
            filas.append({
                "jugador": leg.get("player"),
                "mercado": leg.get("market"),
                "linea": leg.get("line"),
                "prob_estimada": prob_por_leg.get(clave),
                "se_dio": leg.get("state") == "done",
            })

    if not filas:
        return
    try:
        registrar_legs_resueltas(chat_id, ticket_id, filas)
    except Exception:
        log.exception("No pude registrar las legs resueltas para calibración")


def _ticket_id(ticket: dict, legs_raw: list[dict]) -> str:
    """Id estable de un ticket.

    Se arma con lo que identifica la apuesta y NO cambia con el tiempo:
    jugador, mercado y línea de cada tramo, más la etiqueta y la cuota.

    OJO con lo que NO entra acá: el `match`. Cuando el cupón no trae el
    partido, se deduce a partir del jugador y se ESCRIBE en la leg. Si
    el partido formara parte del id, el que muestra la web (con partido
    deducido) sería distinto del que se recalcula al borrar (sin él), y
    el botón × no encontraría nunca la apuesta. Es lo que pasaba.
    """
    piezas = "|".join(sorted(
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
            # No alcanza con "vacío": la IA a veces devuelve un texto que
            # no identifica ningún equipo (guiones, "?", el nombre del
            # mercado). Si no reconocemos DOS equipos, hay que deducirlo.
            if leg.get("player") and len(equipos_en_texto(nombre)) < 2:
                deducido = _partido_del_jugador(leg["player"])
                if deducido:
                    nombre = deducido
                    leg["match"] = deducido
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

        # Los borradores no van a calibración: no son apuestas reales y
        # medirían el modelo contra decisiones que nunca se tomaron.
        if terminado and not ticket.get("borrador"):
            _registrar_para_calibracion(chat_id, ticket_id, grupos, legs_raw)
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
            "borrador": bool(ticket.get("borrador")),
            "id": ticket_id,
            # Una sola leg perdida (o prácticamente decidida en contra,
            # como un pitcher que ya salió del montículo sin cumplir) ya
            # rompe toda la combinada: no hace falta seguir mirándola
            # tramo por tramo.
            "caida": any(
                l.get("state") in ("lost", "dead")
                for g in grupos for l in g.get("legs", [])
            ),
        })

    # Orden útil: lo que está pasando ahora arriba, lo terminado abajo.
    # Antes salían en orden de carga, así que un ticket de ayer podía
    # tapar el que se está jugando.
    def _prioridad(t):
        if t.get("terminado"):
            return 3
        if t.get("caida"):
            return 2
        return 0 if t.get("live") else 1

    salida.sort(key=_prioridad)

    # Resumen para la cabecera: evita tener que sumar a ojo.
    total_legs = sum(t["total"] for t in salida)
    cumplidas_legs = sum(t["done"] for t in salida)

    return {
        "tickets": salida,
        "count": len(salida),
        "resumen": {
            "legs_cumplidas": cumplidas_legs,
            "legs_totales": total_legs,
            "en_vivo": sum(1 for t in salida if t.get("live") and not t.get("terminado")),
            "caidas": sum(1 for t in salida if t.get("caida")),
        },
    }


def detalle_leg(player: str, market: str, line: str) -> dict[str, Any]:
    """Desglose partido-por-partido de una leg puntual. Es lo que pide
    el botón de 'profundizar' en cada leg: no el resumen ('90% en sus
    últimos 10'), sino el detalle de cada uno de esos partidos."""
    # Si el "jugador" es en realidad un equipo, hay que usar el gameLog
    # del equipo: buscarlo en el roster de jugadores no lo encuentra.
    from app.utils.equipos import id_equipo

    if id_equipo(player):
        detalle = estimate_team_detail(player, market, line)
    else:
        detalle = estimate_leg_detail(player, market, line)
    return {
        "player": detalle.player,
        "market": nombre_stake_texto(market, detalle.is_pitcher),
        "side": detalle.side,
        "threshold": detalle.threshold,
        "probability_pct": detalle.probability_pct,
        "avg_value": detalle.avg_value,
        "games": [
            {"date": g.date, "value": g.value, "hit": g.hit} for g in detalle.games
        ],
        **_sugerencias_para(player, market, line),
    }


def _sugerencias_para(player: str, market: str, line: str) -> dict[str, Any]:
    """Líneas alternativas del mismo mercado, para responder "¿me
    convenía pedir más?". Si falla, se devuelve vacío: es información
    extra, no puede tumbar el detalle."""
    try:
        opciones = sugerir_lineas(player, market, line)
    except ProbabilityError:
        return {"alternativas": [], "sugerencia": None}
    except Exception:
        log.exception("No pude calcular alternativas de línea")
        return {"alternativas": [], "sugerencia": None}

    mejor = mejor_alternativa(opciones)
    return {
        "alternativas": [
            {
                "linea": o.linea,
                "side": o.side,
                "pct": o.probabilidad_pct,
                "apostada": o.es_la_apostada,
            }
            for o in opciones
        ],
        "sugerencia": (
            {"linea": mejor.linea, "side": mejor.side, "pct": mejor.probabilidad_pct}
            if mejor else None
        ),
    }


# --- Entrada desde la web ------------------------------------------------

def _estimar_legs(tickets: list[dict]) -> None:
    """Escribe en cada leg la probabilidad estimada ANTES de que se juegue.

    Es el único número honesto para medir calibración después:
    calcularlo más tarde estaría contaminado, porque los "últimos
    partidos" ya incluirían el que se está jugando.
    """
    legs = [leg for t in tickets for leg in t.get("legs", []) if leg.get("player")]
    if not legs:
        return

    # Traer los jugadores de una, en paralelo: de a uno son dos llamadas
    # encadenadas por leg.
    try:
        precalentar_cache([l["player"] for l in legs])
    except Exception:
        log.debug("No pude precalentar para estimar", exc_info=True)

    for leg in legs:
        try:
            est = estimate_leg_probability(
                leg["player"], leg.get("market", ""), leg.get("line", "")
            )
            leg["prob_estimada"] = est.probability_pct
        except Exception:
            # Una leg sin estimación no cuenta para calibración, pero no
            # puede impedir que se guarde la apuesta.
            log.debug("Sin estimación para %s", leg.get("player"), exc_info=True)


def guardar_captura(chat_id: int, imagenes: list[bytes], borrador: bool = False) -> dict[str, Any]:
    """Analiza capturas subidas desde la web y las guarda.

    Es el mismo camino que usa el bot de Telegram, pero sin Telegram:
    con esto la web deja de depender del chat para cargar una apuesta.
    """
    from app.ai.vision import analyze_bet_screenshot
    from app.analysis.tickets import merge_tickets, to_storage, unificar_cupon
    from app.db.database import log_bet_analysis, save_active_bet

    leidos: list[list[dict]] = []
    errores: list[str] = []
    for imagen in imagenes:
        try:
            # Una captura = un cupón: los bloques que la IA lee como
            # apuestas separadas se unen salvo que cada uno traiga su
            # propia cuota total.
            leidos.append(unificar_cupon(normalize(analyze_bet_screenshot(imagen))))
        except Exception as exc:
            log.warning("No pude leer una captura subida por la web: %s", exc)
            errores.append(str(exc))

    if not leidos:
        return {"ok": False, "error": errores[0] if errores else "No pude leer la captura."}

    previos = normalize(get_active_bet(chat_id) or {}) if not borrador else []
    tickets = merge_tickets([previos, *leidos]) if previos else merge_tickets(leidos)

    analisis = to_storage(tickets)
    if borrador:
        for t in analisis.get("bets", []):
            t["borrador"] = True

    # Estimar ANTES de guardar. Este comentario decía antes que la
    # probabilidad "se calcula al armar el estado", y era falso: nadie la
    # calculaba en el camino web. Las apuestas subidas desde la página se
    # guardaban sin prob_estimada, se registraban con el campo vacío y la
    # consulta de calibración las descarta -- por eso el contador no
    # subía aunque los partidos terminaran.
    _estimar_legs(tickets)

    save_active_bet(chat_id, analisis)
    if not borrador:
        try:
            log_bet_analysis(chat_id, analisis)
        except Exception:
            log.exception("No pude guardar el historial")

    return {
        "ok": True,
        "tickets": len(tickets),
        "legs": sum(len(t.get("legs", [])) for t in tickets),
        "errores": errores,
    }


def mejorar_ticket(chat_id: int, ticket_id: str | None = None) -> dict[str, Any]:
    """Versión segura de una apuesta guardada, para la web.

    La meta es siempre OBJETIVO_SEGURO (85%); la calibración corrige
    cuánto confiar en cada estimación antes de compararla contra esa
    meta, no la meta en sí -- ver `_prob_calibrada` en auditoria.py.
    """
    from app.analysis.auditoria import OBJETIVO_SEGURO, version_segura
    from app.analysis.probability import _buscar_jugador_cacheado

    guardada = get_active_bet(chat_id)
    tickets = normalize(guardada or {})
    if not tickets:
        return {"ok": False, "error": "No tenés apuestas cargadas."}

    if ticket_id:
        tickets = [t for t in tickets if _ticket_id(t, t.get("legs", [])) == ticket_id]
        if not tickets:
            return {"ok": False, "error": "No encontré esa apuesta."}

    legs = [leg for t in tickets for leg in t.get("legs", [])]
    tramos, combinada = version_segura(legs, OBJETIVO_SEGURO, chat_id)

    # Equipo de cada jugador, para que la web pueda mostrar de quién es
    # cada uno -- version_segura ya buscó a cada jugador para estimar
    # probabilidad, así que esto es un acierto de caché, no una llamada
    # nueva a la MLB API.
    def _equipo_de(nombre: str) -> str | None:
        try:
            return (_buscar_jugador_cacheado(nombre) or {}).get("team")
        except Exception:
            return None

    return {
        "ok": True,
        "objetivo": OBJETIVO_SEGURO,
        "combinada": combinada,
        "tramos": [
            {
                "player": t.player,
                "equipo": _equipo_de(t.player),
                "match": partido_corto(t.match),
                "market": nombre_stake_texto(t.market),
                "linea_original": t.linea_original,
                "linea_nueva": t.linea_nueva,
                "prob": t.probabilidad,
                "cambio": t.cambio,
                "no_alcanza": t.no_alcanza,
            }
            for t in tramos
        ],
    }
