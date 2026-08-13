"""Ajuste por el PITCHER RIVAL.

El problema que resuelve: que un bateador promedie 1.2 hits no dice nada
por sí solo. Esos 1.2 salen de enfrentar a un abridor cualquiera. Si hoy
le toca un as, su chance real baja; si le toca un abridor castigado,
sube. Es la variable que más mueve la aguja en props de bateo, y las
casas de apuestas la usan — nosotros la ignorábamos por completo.

Cómo se calcula: se compara el rival de hoy contra un pitcher promedio
de la liga usando WHIP (baserunners permitidos por entrada), que es la
medida más directa de "cuánta gente deja llegar a base". Un WHIP más
bajo que el promedio significa un rival más difícil, y la probabilidad
del bateador se corrige hacia abajo.

Lo que este módulo NO hace, a propósito:
- No inventa un ajuste si falta el dato. Sin pitcher probable publicado
  o sin estadísticas suyas, devuelve 1.0 (sin cambios).
- No toca los mercados de PITCHEO. Un prop sobre lo que hace el propio
  lanzador no depende de quién lanza enfrente.
- No aplica correcciones grandes. El tope es deliberadamente conservador:
  el ajuste corrige un sesgo, no reemplaza al modelo.
"""
from __future__ import annotations

from app.mlb.pitchers import get_season_pitching_stats
from app.mlb.players import search_player
from app.utils.logger import get_logger

log = get_logger(__name__)

# WHIP de referencia de la liga (baserunners por entrada). Ronda 1.25-1.30
# en la MLB moderna; se usa 1.28 como centro.
WHIP_LIGA = 1.28

# Cuánto puede mover el ajuste, como máximo, en cada dirección. Un as
# frente a un abridor flojo es una diferencia real pero acotada: si
# permitiéramos correcciones de 2x estaríamos inventando precisión que
# el WHIP por sí solo no tiene.
AJUSTE_MINIMO = 0.85
AJUSTE_MAXIMO = 1.15

# Innings mínimos para creerle al WHIP. Con 10 entradas un WHIP de 0.60
# es ruido, no dominio.
_INNINGS_MINIMOS = 20.0

_cache_whip: dict[str, float | None] = {}


def limpiar_cache_pitchers() -> None:
    _cache_whip.clear()


def _innings_a_float(ip) -> float:
    """La MLB API informa entradas como "45.2" = 45 entradas y 2 outs,
    no 45.2 decimal."""
    try:
        texto = str(ip)
        entero, _, outs = texto.partition(".")
        return int(entero) + (int(outs or 0) / 3)
    except (TypeError, ValueError):
        return 0.0


def whip_del_pitcher(nombre: str) -> float | None:
    """WHIP de la temporada, o None si no hay dato confiable."""
    if not nombre:
        return None
    if nombre in _cache_whip:
        return _cache_whip[nombre]

    resultado: float | None = None
    try:
        jugador = search_player(nombre)
        if jugador and jugador.get("id"):
            stats = get_season_pitching_stats(jugador["id"])
            if stats:
                innings = _innings_a_float(stats.get("inningsPitched"))
                if innings >= _INNINGS_MINIMOS:
                    hits = stats.get("hits", 0)
                    walks = stats.get("baseOnBalls", 0)
                    resultado = round((hits + walks) / innings, 3)
    except Exception:
        log.debug("No pude traer el WHIP de %s", nombre, exc_info=True)

    _cache_whip[nombre] = resultado
    return resultado


def factor_por_pitcher_rival(nombre_pitcher: str | None) -> float:
    """Multiplicador para la probabilidad de un bateador.

    < 1.0 = rival difícil (baja la chance). > 1.0 = rival accesible.
    Exactamente 1.0 cuando no hay datos suficientes: preferimos no
    ajustar antes que ajustar mal.
    """
    if not nombre_pitcher:
        return 1.0

    whip = whip_del_pitcher(nombre_pitcher)
    if whip is None or whip <= 0:
        return 1.0

    # Proporción directa: un rival que permite menos baserunners que el
    # promedio reduce la chance del bateador en esa misma proporción.
    factor = whip / WHIP_LIGA
    return round(max(AJUSTE_MINIMO, min(AJUSTE_MAXIMO, factor)), 3)


def describir_factor(factor: float, nombre_pitcher: str | None) -> str:
    """Texto corto para explicar por qué se ajustó."""
    if factor == 1.0 or not nombre_pitcher:
        return ""
    if factor < 0.95:
        return f"ajustado a la baja: {nombre_pitcher} es un rival duro"
    if factor > 1.05:
        return f"ajustado al alza: {nombre_pitcher} viene siendo castigado"
    return ""
