"""Cliente para The Odds API (https://the-odds-api.com).

Diseñado para ser intercambiable: si mañana cambiás a SportsDataIO u
otro proveedor, solo hace falta un archivo nuevo con la misma interfaz
pública (get_player_props, get_game_odds) y cambiar el import en los
handlers — no tocar lógica de negocio.
"""
from __future__ import annotations

from typing import Any

import requests

from app.config import settings
from app.utils.logger import get_logger

log = get_logger(__name__)

_BASE_URL = "https://api.the-odds-api.com/v4"
_SPORT_KEY = "baseball_mlb"
_TIMEOUT = 10


class OddsClientError(Exception):
    """Error al comunicarse con The Odds API."""


def _get(path: str, params: dict[str, Any]) -> Any:
    if not settings.odds_api_key:
        raise OddsClientError(
            "Falta ODDS_API_KEY. Conseguí una key gratis en the-odds-api.com "
            "y cargala en tu .env / Railway vars."
        )
    params = {**params, "apiKey": settings.odds_api_key}
    url = f"{_BASE_URL}{path}"
    try:
        resp = requests.get(url, params=params, timeout=_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        log.error("Error llamando a %s: %s", url, exc)
        raise OddsClientError(f"Fallo al consultar The Odds API: {exc}") from exc


def get_game_odds(markets: str = "h2h,totals") -> list[dict[str, Any]]:
    """Odds de moneyline/totales para los partidos de MLB de hoy,
    comparando entre casas de apuestas (Bet365, FanDuel, DraftKings, etc.)."""
    data = _get(
        f"/sports/{_SPORT_KEY}/odds",
        params={"regions": "us,eu", "markets": markets, "oddsFormat": "decimal"},
    )
    games = []
    for g in data:
        books = []
        for book in g.get("bookmakers", []):
            books.append(
                {
                    "book": book.get("title"),
                    "markets": book.get("markets", []),
                }
            )
        games.append(
            {
                "away_team": g.get("away_team"),
                "home_team": g.get("home_team"),
                "commence_time": g.get("commence_time"),
                "bookmakers": books,
            }
        )
    return games


def get_player_props(event_id: str, markets: str = "pitcher_strikeouts,batter_hits,batter_home_runs") -> dict[str, Any]:
    """Props de jugador (ponches, hits, HR) para un partido específico.

    event_id se obtiene de get_game_odds() -> no viene en el payload actual,
    hace falta pegarle primero a /events para mapear partido -> event_id.
    Ver get_events().
    """
    return _get(
        f"/sports/{_SPORT_KEY}/events/{event_id}/odds",
        params={"regions": "us", "markets": markets, "oddsFormat": "decimal"},
    )


def get_events() -> list[dict[str, Any]]:
    """Lista de eventos (partidos) con sus event_id, necesarios para
    después pedir props con get_player_props()."""
    return _get(f"/sports/{_SPORT_KEY}/events", params={})
