"""Arma el estado de las apuestas para la web.

Reusa exactamente la misma lógica que el bot de Telegram (tickets,
tracking en vivo, probabilidad). La única diferencia es la salida: acá
devolvemos datos crudos en JSON y el navegador se encarga de dibujar,
en vez de armar texto con emojis.

Es el punto de la arquitectura: una sola fuente de verdad, dos formas
de mostrarla.
"""
from __future__ import annotations

from typing import Any

from app.analysis.live_tracking import get_live_tracking_for_match, track_leg_live
from app.analysis.probability import ProbabilityError, estimate_leg_probability
from app.analysis.tickets import normalize
from app.db.database import get_active_bet
from app.utils.equipos import partido_corto
from app.utils.logger import get_logger
from app.utils.market_labels import nombre_stake
from app.utils.progress_bar import target_needed

log = get_logger(__name__)


def _estado_leg(status) -> str:
    """Traduce el estado interno a una clase que la web entiende."""
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
    except ProbabilityError:
        return None

    objetivo = target_needed(status.threshold, status.side)
    return {
        "player": status.player,
        "market": nombre_stake(leg.get("market", "")) or leg.get("market", ""),
        "line": leg.get("line", ""),
        "odds": leg.get("odds"),
        "current": status.current_value,
        "goal": objetivo,
        "pct": _pct(status.current_value, objetivo, status.already_hit),
        "state": _estado_leg(status),
        "note": status.status_text,
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


def estado_apuestas(chat_id: int) -> dict[str, Any]:
    """Devuelve todos los tickets guardados con su estado actual."""
    guardado = get_active_bet(chat_id)
    tickets = normalize(guardado or {})

    salida: list[dict[str, Any]] = []

    for ticket in tickets:
        legs_raw = ticket.get("legs", [])
        if not legs_raw:
            continue

        live_data = None
        if ticket.get("is_live"):
            try:
                live_data = get_live_tracking_for_match(ticket.get("match", ""))
            except Exception:
                log.exception("Error buscando partido en vivo para la web")

        legs: list[dict[str, Any]] = []
        for leg in legs_raw:
            resultado = None
            if live_data:
                boxscore, live_state = live_data
                resultado = _leg_en_vivo(leg, boxscore, live_state)
            legs.append(resultado or _leg_historica(leg))

        cumplidas = sum(1 for l in legs if l.get("state") == "done")
        cabecera: dict[str, Any] = {
            "match": partido_corto(ticket.get("match")),
            "odds": ticket.get("total_odds"),
            "legs": legs,
            "done": cumplidas,
            "total": len(legs),
            "live": bool(live_data),
        }

        if live_data:
            _, live_state = live_data
            traducido = {
                "Top": "arriba",
                "Bottom": "abajo",
                "Middle": "medio",
                "End": "fin",
            }.get(live_state.get("inning_state") or "", "")
            cabecera.update(
                {
                    "inning": live_state.get("inning"),
                    "inning_state": traducido,
                    "away_score": live_state.get("away_score"),
                    "home_score": live_state.get("home_score"),
                }
            )

        salida.append(cabecera)

    return {"tickets": salida, "count": len(salida)}
