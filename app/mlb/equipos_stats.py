"""Estadísticas por EQUIPO, para los mercados que Stake rotula
"Equipo, ..." (ej. "Equipo, bases por bolas del bateador — Royals Over
2.5").

Es el mismo enfoque que usamos con jugadores -mirar los últimos N
partidos y contar en cuántos se pasó la línea- pero pidiéndole a la MLB
API el gameLog del equipo en vez del de una persona.

Lo que NO cubre este módulo: los mercados de PARTIDO ("Partido, ponches
Under 14.5"), que suman a los dos equipos y dependen sobre todo de
quiénes lanzan ese día. El historial del enfrentamiento no sirve porque
cada día lanza otro; estimarlo con esto daría un número lindo y falso.
Esos siguen marcados como "no lo sigo".
"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.mlb.http import get
from app.utils.logger import get_logger

log = get_logger(__name__)


def get_recent_team_games(
    team_id: int, grupo: str = "hitting", last_n: int = 10, season: int | None = None
) -> list[dict[str, Any]]:
    """Últimos N partidos del equipo con sus totales.

    grupo: "hitting" (lo que produjo el equipo bateando) o "pitching"
    (lo que permitió su cuerpo de lanzadores).
    """
    season = season or date.today().year
    data = get(
        f"/teams/{team_id}/stats",
        params={"stats": "gameLog", "group": grupo, "season": season},
    )

    # Mismo cuidado que en players.py: `stats` puede venir como lista
    # vacía si el equipo no tiene partidos cargados en esa categoría.
    bloques = data.get("stats") or []
    splits = bloques[0].get("splits", []) if bloques else []

    juegos: list[dict[str, Any]] = []
    for s in splits[-last_n:]:
        stat = s.get("stat", {})
        if grupo == "hitting":
            juegos.append({
                "date": s.get("date"),
                "hits": stat.get("hits", 0),
                "runs": stat.get("runs", 0),
                "rbi": stat.get("rbi", 0),
                "home_runs": stat.get("homeRuns", 0),
                "walks": stat.get("baseOnBalls", 0),
                "strikeouts": stat.get("strikeOuts", 0),
                "total_bases": stat.get("totalBases", 0),
                "stolen_bases": stat.get("stolenBases", 0),
                "doubles": stat.get("doubles", 0),
                "triples": stat.get("triples", 0),
                "singles": max(
                    0,
                    stat.get("hits", 0)
                    - stat.get("doubles", 0)
                    - stat.get("triples", 0)
                    - stat.get("homeRuns", 0),
                ),
            })
        else:
            juegos.append({
                "date": s.get("date"),
                "strikeouts": stat.get("strikeOuts", 0),
                "walks": stat.get("baseOnBalls", 0),
                "hits_allowed": stat.get("hits", 0),
                "earned_runs": stat.get("earnedRuns", 0),
                "runs_allowed": stat.get("runs", 0),
            })

    juegos.reverse()  # más reciente primero, igual que los de jugador
    return juegos
