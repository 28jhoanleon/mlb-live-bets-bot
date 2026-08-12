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
        "bats": p.get("batSide", {}).get("code"),  # 'L' / 'R' / 'S' (switch)
        "throws": p.get("pitchHand", {}).get("code"),  # idem, mano de lanzar
    }


# Bajo esta muestra, un split contra una mano no dice nada -- es la
# diferencia entre "20 turnos" y "temporada completa". Preferimos no
# mostrar nada antes que mostrar un dato que parece sólido y es ruido.
_MUESTRA_MINIMA_SPLIT = 20


def get_hitting_split_vs_hand(
    player_id: int, hand: str, season: int | None = None
) -> dict[str, Any] | None:
    """Cómo batea ESTE bateador en la temporada contra pitchers de esa
    mano ('L' o 'R'). Es informativo -- no se usa para calcular
    probabilidad, solo para mostrar contexto extra en el mensaje.

    None si la API no tiene el split, o si la muestra es muy chica para
    decir algo útil."""
    if hand not in ("L", "R"):
        return None
    season = season or date.today().year
    sit_code = "vl" if hand == "L" else "vr"
    try:
        data = get(
            f"/people/{player_id}/stats",
            params={
                "stats": "statSplits",
                "group": "hitting",
                "sitCodes": sit_code,
                "season": season,
            },
        )
    except Exception:
        log.debug("No pude traer el split vs %s para %s", hand, player_id, exc_info=True)
        return None

    bloques = data.get("stats") or []
    splits = bloques[0].get("splits", []) if bloques else []
    if not splits:
        return None
    stat = splits[0].get("stat", {})
    at_bats = stat.get("atBats", 0)
    if at_bats < _MUESTRA_MINIMA_SPLIT:
        return None
    return {
        "hand": hand,
        "at_bats": at_bats,
        "avg": stat.get("avg"),
        "home_runs": stat.get("homeRuns", 0),
        "hits": stat.get("hits", 0),
    }


def get_season_hitting_stats(player_id: int, season: int | None = None) -> dict[str, Any] | None:
    season = season or date.today().year
    data = get(
        f"/people/{player_id}/stats",
        params={"stats": "season", "group": "hitting", "season": season},
    )
    # `stats` puede venir como lista VACÍA (no [{}]) cuando el
    # jugador no tiene partidos cargados en esa categoría: por
    # ejemplo un pitcher recién subido, o un bateador al que se
    # le pide gameLog de pitcheo. El default [{}] no cubre ese
    # caso -- el índice [0] reventaba con IndexError.
    bloques = data.get("stats") or []
    splits = bloques[0].get("splits", []) if bloques else []
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
    # `stats` puede venir como lista VACÍA (no [{}]) cuando el
    # jugador no tiene partidos cargados en esa categoría: por
    # ejemplo un pitcher recién subido, o un bateador al que se
    # le pide gameLog de pitcheo. El default [{}] no cubre ese
    # caso -- el índice [0] reventaba con IndexError.
    bloques = data.get("stats") or []
    splits = bloques[0].get("splits", []) if bloques else []
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
                "total_bases": stat.get("totalBases", 0),
                "doubles": stat.get("doubles", 0),
                "triples": stat.get("triples", 0),
                # La API no da los sencillos: son los hits que no fueron
                # doble, triple ni jonrón.
                "singles": max(
                    0,
                    stat.get("hits", 0)
                    - stat.get("doubles", 0)
                    - stat.get("triples", 0)
                    - stat.get("homeRuns", 0),
                ),
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
