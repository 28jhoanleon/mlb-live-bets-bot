"""Todo lo relacionado a calendario y pitchers probables.
Separado de live.py porque son datos que se piden con distinta frecuencia
(schedule cambia una vez al día, live cambia cada pocos segundos)."""
from __future__ import annotations

from datetime import date
from typing import Any

from app.mlb.http import get
from app.utils.logger import get_logger

log = get_logger(__name__)


def get_schedule(target_date: date | None = None) -> list[dict[str, Any]]:
    """Devuelve los partidos del día con pitchers probables incluidos."""
    target_date = target_date or date.today()
    data = get(
        "/schedule",
        params={
            "sportId": 1,
            "date": target_date.isoformat(),
            "hydrate": "probablePitcher,team,linescore",
        },
    )

    games: list[dict[str, Any]] = []
    for day in data.get("dates", []):
        for g in day.get("games", []):
            teams = g.get("teams", {})
            away = teams.get("away", {})
            home = teams.get("home", {})
            games.append(
                {
                    "game_pk": g.get("gamePk"),
                    "status": g.get("status", {}).get("detailedState"),
                    "away_team": away.get("team", {}).get("name"),
                    "home_team": home.get("team", {}).get("name"),
                    "venue": g.get("venue", {}).get("name"),
                    "game_time_utc": g.get("gameDate"),
                    "away_pitcher": _pitcher_name(away),
                    "home_pitcher": _pitcher_name(home),
                }
            )
    return games


def _pitcher_name(side: dict[str, Any]) -> str | None:
    pitcher = side.get("probablePitcher")
    return pitcher.get("fullName") if pitcher else None
