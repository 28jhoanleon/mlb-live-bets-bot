"""Estadísticas por EQUIPO, para los mercados que Stake rotula
"Equipo, ..." (bases por bolas del equipo, hits del equipo, etc.).

Hasta ahora estos mercados se mostraban como "no los sigo": el bot solo
sabía estimar con el historial de un jugador. La MLB Stats API expone
gameLog a nivel equipo igual que a nivel jugador, así que es la misma
idea aplicada un nivel más arriba.

Lo que NO cubre esto, a propósito: los mercados de PARTIDO ("Partido,
ponches Under 14.5"), que son la suma de los dos equipos y dependen casi
enteramente de quiénes lanzan ese día. El historial del partido no
sirve porque cada día lanza otro pitcher. Preferimos decir "no sé" antes
que dar un número que suene preciso y no lo sea.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.mlb.http import get
from app.utils.logger import get_logger

log = get_logger(__name__)


def _splits(data: dict[str, Any]) -> list[dict[str, Any]]:
    # Mismo cuidado que en players/pitchers: `stats` puede venir como
    # lista vacía y el índice [0] reventaría.
    bloques = data.get("stats") or []
    return bloques[0].get("splits", []) if bloques else []


def get_recent_team_games(
    team_id: int, last_n: int = 10, group: str = "hitting", season: int | None = None
) -> list[dict[str, Any]]:
    """Últimos N partidos del equipo con sus totales de ofensiva.

    group: "hitting" o "pitching" — Stake tiene mercados de los dos
    lados (hits del equipo, ponches que reparte su pitcheo).
    """
    season = season or date.today().year
    data = get(
        f"/teams/{team_id}/stats",
        params={"stats": "gameLog", "group": group, "season": season},
    )

    juegos = []
    for split in _splits(data)[:last_n]:
        stat = split.get("stat", {})
        juegos.append({
            "date": split.get("date"),
            "hits": stat.get("hits", 0),
            "runs": stat.get("runs", 0),
            "rbi": stat.get("rbi", 0),
            "home_runs": stat.get("homeRuns", 0),
            "walks": stat.get("baseOnBalls", 0),
            "strikeouts": stat.get("strikeOuts", 0),
            "stolen_bases": stat.get("stolenBases", 0),
            "total_bases": stat.get("totalBases", 0),
            "doubles": stat.get("doubles", 0),
            "triples": stat.get("triples", 0),
        })
    return juegos


# Qué campo del gameLog corresponde a cada mercado de equipo. Se mantiene
# como tabla explícita y no adivinando por texto: si aparece un mercado
# nuevo preferimos no reconocerlo antes que mapearlo mal.
_CAMPOS_EQUIPO = {
    "hits": ["hits"],
    "golpes": ["hits"],
    "runs": ["runs"],
    "carreras": ["runs"],
    "walks": ["walks"],
    "caminatas": ["walks"],
    "bases por bolas": ["walks"],
    "base on balls": ["walks"],
    "strikeouts": ["strikeouts"],
    "ponches": ["strikeouts"],
    "home runs": ["home_runs"],
    "jonrones": ["home_runs"],
    "total bases": ["total_bases"],
    "bases totales": ["total_bases"],
    "stolen bases": ["stolen_bases"],
    "bases robadas": ["stolen_bases"],
}


def campos_de_mercado_equipo(market_text: str) -> list[str] | None:
    """Traduce el texto del mercado al campo del gameLog. None si no lo
    reconocemos — mejor avisar que estimar con el dato equivocado."""
    from app.analysis.probability import _normalize

    m = _normalize(market_text).replace("_", " ")
    # De más específico a más general: "bases por bolas" antes que "bases".
    for clave in sorted(_CAMPOS_EQUIPO, key=len, reverse=True):
        if clave in m:
            return _CAMPOS_EQUIPO[clave]
    return None


def es_mercado_de_pitcheo(market_text: str) -> bool:
    """Los ponches que un equipo REPARTE salen de su pitcheo; los que se
    COME, de su ofensiva. Stake los distingue en el rótulo."""
    from app.analysis.probability import _normalize

    m = _normalize(market_text)
    return any(p in m for p in ("pitcher", "pitcheo", "permitid", "allowed"))
