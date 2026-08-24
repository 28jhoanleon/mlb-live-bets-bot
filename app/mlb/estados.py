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

from app.utils.tiempo import zona_local

# "Warmup" NO es en curso: la MLB lo marca ~20 minutos ANTES del primer
# lanzamiento, y por eso la web mostraba el partido como live cuando
# todavía no había empezado. "Delayed" tampoco: es demora, no juego.
EN_CURSO = ("In Progress", "Manager challenge")

# Estados de antesala: el partido es inminente pero no arrancó. Se
# distinguen de "Scheduled" para poder mostrar "está por empezar" sin
# mentir diciendo que ya está en juego.
POR_EMPEZAR = ("Warmup", "Pre-Game", "Delayed")
TERMINADO = ("Final", "Game Over", "Completed Early")
# Los que ya tienen boxscore para consultar.
CON_DATOS = EN_CURSO + TERMINADO

# Cuántos días hacia atrás (y hacia adelante) buscar un partido antes de
# darlo por no encontrado.
DIAS_HACIA_ATRAS = 3


def momento_de_la_captura(match_datetime: str | None) -> datetime | None:
    """Interpreta el 'match_datetime' que la visión leyó de la captura.

    Viene en hora LOCAL del usuario ("2026-07-30 13:10") porque así lo
    muestra la casa de apuestas; el calendario de la MLB usa UTC, así
    que hay que convertirlo antes de comparar. Devuelve None si el dato
    falta o no se entiende -en ese caso el que llama debe caer al
    respaldo por cercanía, no inventar una fecha."""
    if not match_datetime:
        return None
    try:
        ingenuo = datetime.fromisoformat(str(match_datetime).strip())
    except (ValueError, TypeError):
        return None
    if ingenuo.tzinfo is not None:
        return ingenuo.astimezone(timezone.utc)
    return ingenuo.replace(tzinfo=zona_local()).astimezone(timezone.utc)


def mas_cercano_a(candidatos: list[dict], referencia: datetime) -> dict | None:
    """De varios partidos que matchean por nombre de equipo, elige el más
    cercano a un momento de REFERENCIA dado."""
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
        return abs((referencia - momento).total_seconds())

    return min(candidatos, key=_distancia_segundos)


def mas_cercano_a_ahora(candidatos: list[dict]) -> dict | None:
    """De varios partidos que matchean por nombre de equipo -puede haber
    más de uno si los mismos dos equipos juegan una serie de varios
    días- elige el de fecha/hora más cercana a AHORA MISMO.

    OJO: esto es un RESPALDO, no la forma correcta de elegir. Adivina
    por proximidad temporal porque no tiene mejor información. Si la
    apuesta trae la fecha del partido (match_datetime, leído de la
    captura), hay que usar `mas_cercano_a` con esa fecha: es el único
    dato que de verdad distingue dos partidos del mismo cruce en días
    consecutivos.

    Bug real que motivó todo esto: un ticket de AYER y otro de HOY entre
    los mismos dos equipos se pisaban entre sí, y ninguna heurística
    basada en "ahora" puede resolver eso bien -el ticket viejo siempre
    va a querer engancharse al partido nuevo."""
    return mas_cercano_a(candidatos, datetime.now(timezone.utc))
