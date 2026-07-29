"""Datos de pitchers: stats de temporada y forma reciente.
Reusa search_player de players.py (la búsqueda de persona es la misma
API, no depende de si es bateador o pitcher)."""
from __future__ import annotations

from datetime import date
from typing import Any

from app.mlb.http import get
from app.utils.logger import get_logger

log = get_logger(__name__)


def innings_pitched_to_outs(ip: str | float) -> int:
    """Convierte '5.1' (5 innings + 1 out) a outs totales: 16."""
    try:
        ip_str = str(ip)
        whole, _, frac = ip_str.partition(".")
        return int(whole) * 3 + int(frac or 0)
    except (ValueError, TypeError):
        return 0


def get_season_pitching_stats(player_id: int, season: int | None = None) -> dict[str, Any] | None:
    season = season or date.today().year
    data = get(
        f"/people/{player_id}/stats",
        params={"stats": "season", "group": "pitching", "season": season},
    )
    splits = data.get("stats", [{}])[0].get("splits", [])
    return splits[0].get("stat", {}) if splits else None


def get_recent_pitching_games(
    player_id: int, last_n: int = 5, season: int | None = None
) -> list[dict[str, Any]]:
    """Últimos N starts/apariciones: outs registrados, K, BB, hits
    permitidos, carreras — para estimar ritmo reciente de un pitcher."""
    season = season or date.today().year
    data = get(
        f"/people/{player_id}/stats",
        params={"stats": "gameLog", "group": "pitching", "season": season},
    )
    splits = data.get("stats", [{}])[0].get("splits", [])
    games = []
    for s in splits[-last_n:]:
        stat = s.get("stat", {})
        ip = stat.get("inningsPitched", "0.0")
        games.append(
            {
                "date": s.get("date"),
                "innings_pitched": ip,
                "outs": innings_pitched_to_outs(ip),
                "strikeouts": stat.get("strikeOuts", 0),
                "walks": stat.get("baseOnBalls", 0),
                "hits_allowed": stat.get("hits", 0),
                "earned_runs": stat.get("earnedRuns", 0),
            }
        )
    return games


def average_outs_per_start(games: list[dict[str, Any]]) -> float:
    if not games:
        return 0.0
    return round(sum(g["outs"] for g in games) / len(games), 1)


def average_strikeouts_per_start(games: list[dict[str, Any]]) -> float:
    if not games:
        return 0.0
    return round(sum(g["strikeouts"] for g in games) / len(games), 1)
