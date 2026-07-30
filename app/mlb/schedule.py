"""Todo lo relacionado a calendario y pitchers probables.
Separado de live.py porque son datos que se piden con distinta frecuencia
(schedule cambia una vez al día, live cambia cada pocos segundos)."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from app.mlb.estados import CON_DATOS, DIAS_HACIA_ATRAS
from app.mlb.http import get
from app.utils.logger import get_logger
from app.utils.tiempo import hoy_local

log = get_logger(__name__)


def get_schedule(target_date: date | None = None) -> list[dict[str, Any]]:
    """Devuelve los partidos del día (hora de Argentina) con pitchers
    probables incluidos."""
    target_date = target_date or hoy_local()
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


# --- Caché del calendario -------------------------------------------------
#
# La web consulta cada 30 segundos y cada ticket necesita saber si su
# partido arrancó. Sin caché serían varias llamadas idénticas por minuto
# a la MLB Stats API. El calendario del día cambia poco, así que lo
# guardamos un ratito.

_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_TTL_SEGUNDOS = 45


def get_schedule_cacheado(target_date: date | None = None) -> list[dict[str, Any]]:
    """Igual que get_schedule pero reutiliza el resultado por unos segundos."""
    import time

    clave = (target_date or hoy_local()).isoformat()
    ahora = time.time()

    guardado = _CACHE.get(clave)
    if guardado and (ahora - guardado[0]) < _TTL_SEGUNDOS:
        return guardado[1]

    datos = get_schedule(target_date)
    _CACHE[clave] = (ahora, datos)
    return datos


def limpiar_cache() -> None:
    """Para los tests, y por si hace falta forzar una recarga."""
    _CACHE.clear()


def buscar_partido(away_hint: str, home_hint: str) -> dict[str, Any] | None:
    """Encuentra el partido que coincide con esos equipos.

    A diferencia de find_live_game_by_teams, devuelve el partido ESTÉ O NO
    en vivo. Hace falta para saber el horario y para detectar el momento en
    que arranca: si solo miráramos los que ya están en curso, una apuesta
    cargada antes del primer lanzamiento nunca pasaría a modo en vivo.
    """
    if not away_hint:
        return None
    a = away_hint.lower()
    h = (home_hint or "").lower()

    def _coincide(g: dict[str, Any]) -> bool:
        away = (g.get("away_team") or "").lower()
        home = (g.get("home_team") or "").lower()
        return a in away or (h and h in home) or (h and h in away) or a in home

    # Un partido nocturno (23:10, por ejemplo) puede seguir en curso o
    # recién haber terminado pasada la medianoche en Argentina -momento
    # en que hoy_local() ya pasó al día siguiente y ese partido
    # desaparece de "la cartelera de hoy". Y si el usuario recién vuelve
    # a mirar el ticket más tarde, puede haber pasado más de un día
    # entero. Por eso miramos varios días hacia atrás, del más reciente
    # al más viejo, pero solo nos quedamos con una entrada de un día
    # anterior si de verdad tiene datos (en curso o terminado): si no,
    # puede haber un partido FUTURO entre los mismos equipos hoy (series
    # de varios días) y ese es el que corresponde mostrar.
    for dias_atras in range(1, DIAS_HACIA_ATRAS + 1):
        dia = hoy_local() - timedelta(days=dias_atras)
        for g in get_schedule_cacheado(dia):
            if _coincide(g) and g.get("status") in CON_DATOS:
                return g

    for g in get_schedule_cacheado():
        if _coincide(g):
            return g
    return None
