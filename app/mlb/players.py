"""Datos de bateadores: búsqueda de jugador, stats de temporada y
forma reciente (últimos N partidos)."""
from __future__ import annotations

from datetime import date
from typing import Any

from app.mlb.http import get
from app.utils.logger import get_logger

log = get_logger(__name__)


# Padrón completo de la temporada, para no depender de /people/search.
#
# Ese endpoint devuelve 403 de forma intermitente (se vio en producción),
# y cuando falla NO hay jugador, no hay equipo, no hay partido deducido y
# no hay datos en vivo: se cae toda la cadena. El listado de la
# temporada es una sola llamada y queda en memoria.
_PADRON: dict[str, dict[str, Any]] | None = None


def _clave(nombre: str) -> str:
    from app.analysis.probability import _normalize

    return _normalize(nombre)


def _cargar_padron() -> dict[str, dict[str, Any]]:
    global _PADRON
    if _PADRON is not None:
        return _PADRON

    from datetime import date

    padron: dict[str, dict[str, Any]] = {}
    try:
        data = get("/sports/1/players", params={"season": date.today().year})
        for p in data.get("people", []):
            if p.get("fullName"):
                padron[_clave(p["fullName"])] = p
        log.info("Padrón de jugadores cargado: %d", len(padron))
    except Exception:
        log.warning("No pude cargar el padrón de jugadores", exc_info=True)

    _PADRON = padron
    return padron


def limpiar_padron() -> None:
    global _PADRON
    _PADRON = None


def _buscar_en_padron(name: str) -> dict[str, Any] | None:
    from difflib import SequenceMatcher

    padron = _cargar_padron()
    if not padron:
        return None

    buscado = _clave(name)
    if buscado in padron:
        return padron[buscado]

    # Tolerante a errores de tipeo de la IA, igual que en el boxscore.
    mejor, ratio_mejor = None, 0.0
    for clave, datos in padron.items():
        ratio = SequenceMatcher(None, buscado, clave).ratio()
        if ratio > ratio_mejor:
            mejor, ratio_mejor = datos, ratio
    return mejor if ratio_mejor >= 0.88 else None


def search_player(name: str) -> dict[str, Any] | None:
    """Busca un jugador por nombre.

    Intenta /people/search y, si falla o no encuentra, cae al padrón de
    la temporada. El respaldo existe porque ese endpoint devuelve 403 de
    a ratos, y sin jugador no hay equipo, ni partido, ni datos en vivo.
    """
    p = None
    try:
        # hydrate=currentTeam: sin esto la búsqueda devuelve al jugador
        # PERO SIN su equipo, y sin equipo no se puede deducir a qué
        # partido pertenece la leg. Era el eslabón que faltaba.
        data = get(
            "/people/search",
            params={"names": name, "hydrate": "currentTeam"},
        )
        gente = data.get("people", [])
        if gente:
            p = gente[0]
    except Exception:
        log.info("people/search falló para %s, uso el padrón", name)

    if p is None:
        p = _buscar_en_padron(name)
    if p is None:
        return None

    # Segundo intento por el equipo: algunos endpoints no lo incluyen ni
    # con hydrate. La ficha individual sí lo trae siempre.
    if not p.get("currentTeam", {}).get("name") and p.get("id"):
        try:
            ficha = get(f"/people/{p['id']}", params={"hydrate": "currentTeam"})
            completos = ficha.get("people", [])
            if completos and completos[0].get("currentTeam"):
                p = {**p, "currentTeam": completos[0]["currentTeam"]}
        except Exception:
            log.info("No pude traer el equipo de %s", name)

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
