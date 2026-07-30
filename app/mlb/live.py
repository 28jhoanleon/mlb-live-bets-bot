"""Estado en vivo de partidos: inning, outs, score, corredores en base."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from app.config import settings
from app.mlb.estados import (
    CON_DATOS,
    DIAS_HACIA_ATRAS,
    EN_CURSO,
    mas_cercano_a,
    mas_cercano_a_ahora,
    momento_de_la_captura,
)
from app.mlb.http import MLBClientError, get
from app.mlb.schedule import get_schedule
from app.utils.logger import get_logger
from app.utils.tiempo import hoy_local

log = get_logger(__name__)


def get_live_game(game_pk: int) -> dict[str, Any]:
    """Feed en vivo de un partido puntual. Vive bajo /api/v1.1, no /api/v1."""
    live_base = settings.mlb_stats_base_url.replace("/api/v1", "/api/v1.1")
    data = get(f"/game/{game_pk}/feed/live", base_url=live_base)
    return _parse_live_game(data)


def _parse_live_game(data: dict[str, Any]) -> dict[str, Any]:
    live = data.get("liveData", {})
    linescore = live.get("linescore", {})
    game_data = data.get("gameData", {})

    offense = linescore.get("offense", {})
    bases = {
        "first": bool(offense.get("first")),
        "second": bool(offense.get("second")),
        "third": bool(offense.get("third")),
    }

    return {
        "status": game_data.get("status", {}).get("detailedState"),
        "inning": linescore.get("currentInning"),
        "inning_state": linescore.get("inningState"),
        "outs": linescore.get("outs"),
        "away_score": linescore.get("teams", {}).get("away", {}).get("runs"),
        "home_score": linescore.get("teams", {}).get("home", {}).get("runs"),
        "away_team": game_data.get("teams", {}).get("away", {}).get("name"),
        "home_team": game_data.get("teams", {}).get("home", {}).get("name"),
        "bases": bases,
        "balls": linescore.get("balls"),
        "strikes": linescore.get("strikes"),
        "current_pitcher": linescore.get("defense", {}).get("pitcher", {}).get("fullName"),
        "current_batter": linescore.get("offense", {}).get("batter", {}).get("fullName"),
    }


def get_live_boxscore(game_pk: int) -> dict[str, Any]:
    """Stats de bateo y pitcheo de CADA jugador en el partido en curso.
    Clave: nombre completo del jugador. Sirve para trackear en vivo si
    una prop ya se cumplió (ej. 'Woo lleva 14 outs de 15 necesarios')."""
    live_base = settings.mlb_stats_base_url.replace("/api/v1", "/api/v1.1")
    data = get(f"/game/{game_pk}/feed/live", base_url=live_base)
    return _parse_boxscore(data)


def _parse_boxscore(data: dict[str, Any]) -> dict[str, Any]:
    box = data.get("liveData", {}).get("boxscore", {})
    players: dict[str, Any] = {}
    for side in ("away", "home"):
        team = box.get("teams", {}).get(side, {})
        team_players = team.get("players", {})
        # Orden en que el equipo usó a sus pitchers. El ÚLTIMO de la
        # lista es quien está lanzando ahora por ese equipo. Comparar
        # contra esto (y no contra "el pitcher que lanza en este momento
        # en el partido") evita el falso positivo de dar por sustituido
        # a un pitcher cuyo equipo simplemente está bateando.
        team_pitcher_ids = team.get("pitchers", []) or []
        last_pitcher_id = team_pitcher_ids[-1] if team_pitcher_ids else None

        for _, p in team_players.items():
            person = p.get("person", {})
            name = person.get("fullName")
            if not name:
                continue
            player_id = person.get("id")
            batting = p.get("stats", {}).get("batting", {})
            pitching = p.get("stats", {}).get("pitching", {})
            game_status = p.get("gameStatus", {})
            players[name] = {
                "player_id": player_id,
                "team_side": side,
                "batting_order": p.get("battingOrder"),
                "is_current_batter": game_status.get("isCurrentBatter", False),
                "is_current_pitcher": game_status.get("isCurrentPitcher", False),
                "is_on_bench": game_status.get("isOnBench", False),
                "is_substitute": game_status.get("isSubstitute", False),
                # True si es el último pitcher usado por SU equipo
                "is_team_last_pitcher": (
                    player_id is not None and player_id == last_pitcher_id
                ),
                "team_pitcher_count": len(team_pitcher_ids),
                "batting": {
                    "hits": batting.get("hits", 0),
                    "runs": batting.get("runs", 0),
                    "rbi": batting.get("rbi", 0),
                    "home_runs": batting.get("homeRuns", 0),
                    "strikeouts": batting.get("strikeOuts", 0),
                    "walks": batting.get("baseOnBalls", 0),
                    "stolen_bases": batting.get("stolenBases", 0),
                },
                "pitching": {
                    "innings_pitched": pitching.get("inningsPitched", "0.0"),
                    "outs": _ip_to_outs(pitching.get("inningsPitched", "0.0")),
                    "strikeouts": pitching.get("strikeOuts", 0),
                    "walks": pitching.get("baseOnBalls", 0),
                    "hits_allowed": pitching.get("hits", 0),
                    "earned_runs": pitching.get("earnedRuns", 0),
                },
            }
    return players


def _ip_to_outs(ip: str) -> int:
    try:
        whole, _, frac = str(ip).partition(".")
        return int(whole) * 3 + int(frac or 0)
    except (ValueError, TypeError):
        return 0


def get_live_games_today() -> list[dict[str, Any]]:
    """Filtra el schedule de hoy y devuelve SOLO los partidos en curso
    ahora mismo, con su estado en vivo ya resuelto. La usa /live, que
    tiene que mostrar partidos en curso — no terminados."""
    games = get_schedule()
    live_games = []
    for g in games:
        if g["status"] in EN_CURSO:
            try:
                live = get_live_game(g["game_pk"])
                live_games.append({**g, **live})
            except MLBClientError:
                continue
    return live_games


def find_live_game_by_teams(
    away_hint: str, home_hint: str, match_datetime: str | None = None
) -> int | None:
    """Busca el partido de esos equipos más cercano a AHORA y devuelve su
    game_pk sólo si ya tiene datos (en curso o terminado).

    El orden importa y es la parte delicada: primero se elige el partido
    CORRECTO entre todos los del calendario -sin importar su estado- y
    recién después se mira si tiene datos. Al revés (filtrar por "tiene
    datos" y después elegir el más cercano) el partido de HOY que todavía
    no arrancó queda fuera del pool de candidatos, y gana por default el
    partido YA JUGADO de ayer entre esos mismos equipos: la web terminaba
    mostrando el resultado de ayer sobre un partido que no había
    empezado.

    Si el más cercano todavía no arrancó, devuelve None -que es lo
    correcto: no hay datos en vivo, y la leg cae al histórico.
    """

    def _coincide(g: dict[str, Any]) -> bool:
        away = (g.get("away_team") or "").lower()
        home = (g.get("home_team") or "").lower()
        ah, hh = away_hint.lower(), home_hint.lower()
        return ah in away or hh in home or hh in away or ah in home

    candidatos: list[dict[str, Any]] = []
    for offset in range(-DIAS_HACIA_ATRAS, 2):  # de N días atrás hasta mañana
        dia = hoy_local() + timedelta(days=offset)
        candidatos.extend(g for g in get_schedule(dia) if _coincide(g))

    momento = momento_de_la_captura(match_datetime)
    elegido = (
        mas_cercano_a(candidatos, momento)
        if momento is not None
        else mas_cercano_a_ahora(candidatos)
    )
    if not elegido or elegido.get("status") not in CON_DATOS:
        return None
    return elegido.get("game_pk")
