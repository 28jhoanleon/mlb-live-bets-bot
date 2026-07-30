"""Estados de partido de la MLB Stats API, en un solo lugar.

Antes vivían duplicados: app/mlb/live.py tenía su propia lista (para
decidir qué partidos buscar por game_pk) y app/web/service.py otra
distinta (para decidir si vale la pena pedir datos en vivo). Las dos
se desincronizaron: a la de live.py le faltaban los estados de
partido TERMINADO. Resultado: service.py creía que un partido Final
tenía datos disponibles, pero la búsqueda del game_pk por debajo lo
descartaba siempre por no estar "en curso" — la leg caía al promedio
histórico aunque el partido ya hubiera terminado.
"""
from __future__ import annotations

from datetime import datetime, timezone

EN_CURSO = ("In Progress", "Manager challenge", "Warmup", "Delayed")
TERMINADO = ("Final", "Game Over", "Completed Early")
CON_DATOS = EN_CURSO + TERMINADO

# Cuántos días hacia atrás (y hacia adelante) buscar un partido antes de
# darlo por no encontrado.
DIAS_HACIA_ATRAS = 3


def mas_cercano_a_ahora(candidatos: list[dict]) -> dict | None:
    """De varios partidos que matchean por nombre de equipo -puede haber
    más de uno si los mismos dos equipos juegan una serie de varios
    días- elige el de fecha/hora más cercana a AHORA MISMO, sea pasado
    o futuro.

    Bug real que esto arregla: al preferir ciegamente "cualquiera con
    datos" (En curso o Final) por sobre uno programado, un ticket sobre
    el partido de MAÑANA de una serie terminaba mostrando el resultado
    de un partido de la MISMA serie ya jugado -distinto día, mismos
    equipos- como si fuera el que correspondía."""
    if not candidatos:
        return None

    def _distancia_segundos(g: dict) -> float:
        crudo = g.get("game_time_utc")
        if not crudo:
            return float("inf")
        try:
            momento = datetime.fromisoformat(crudo.replace("Z", "+00:00"))
        except ValueError:
            return float("inf")
        return abs((datetime.now(timezone.utc) - momento).total_seconds())

    return min(candidatos, key=_distancia_segundos)
