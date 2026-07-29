"""Datos de bateadores: búsqueda de jugador, stats de temporada y
forma reciente (últimos N partidos)."""
from __future__ import annotations

from datetime import date
from typing import Any

from app.mlb.http import get
from app.utils.logger import get_logger

log = get_logger(__name__)


def search_player(name: str) -> dict[str, Any] | None:
    """Busca un jugador por nombre completo. Si hay varios resultados
    (nombres comunes), devuelve el primero — para desambiguar mejor
    habría que cruzar con el equipo del partido."""
    data = get("/people/search", params={"names": name})
    people = data.get("people", [])
    if not people:
        return None
    p = people[0]
    return {
        "id": p.get("id"),
        "full_name": p.get("fullName"),
        "team": p.get("currentTeam", {}).get("name"),
        "position": p.get("primaryPosition", {}).get("type"),  # 'Pitcher' o 'Hitter/Outfielder/etc'
    }


def get_season_hitting_stats(player_id: int, season: int | None = None) -> dict[str, Any] | None:
    season = season or date.today().year
    data = get(
        f"/people/{player_id}/stats",
        params={"stats": "season", "group": "hitting", "season": season},
    )
    splits = data.get("stats", [{}])[0].get("splits", [])
    return splits[0].get("stat", {}) if splits else None


def get_recent_hitting_games(
    player_id: int, last_n: int = 10, season: int | None = None
) -> list[dict[str, Any]]:
    """Últimos N partidos con hits, runs, rbi, HR, K, BB — para estimar
    forma reciente en vez de solo el promedio de toda la temporada."""
    season = season or date.today().year
    data = get(
        f"/people/{player_id}/stats",
        params={"stats": "gameLog", "group": "hitting", "season": season},
    )
    splits = data.get("stats", [{}])[0].get("splits", [])
    games = []
    for s in splits[-last_n:]:
        stat = s.get("stat", {})
        games.append(
            {
                "date": s.get("date"),
                "hits": stat.get("hits", 0),
                "runs": stat.get("runs", 0),
                "rbi": stat.get("rbi", 0),
                "at_bats": stat.get("atBats", 0),
                "home_runs": stat.get("homeRuns", 0),
                "strikeouts": stat.get("strikeOuts", 0),
                "walks": stat.get("baseOnBalls", 0),
                "stolen_bases": stat.get("stolenBases", 0),
            }
        )
    return games


def average_per_game(games: list[dict[str, Any]], *fields: str) -> float:
    """Promedio de la suma de los campos indicados por partido.
    Ej: average_per_game(games, 'hits', 'runs', 'rbi') para H+R+RBI."""
    if not games:
        return 0.0
    total = sum(sum(g.get(f, 0) for f in fields) for g in games)
    return round(total / len(games), 2)
