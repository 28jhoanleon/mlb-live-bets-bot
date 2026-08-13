"""Ajuste por el pitcher rival.

El problema que resuelve: que un bateador promedie 1.2 hits no dice lo
mismo si mañana enfrenta a un as o a un abridor castigado. El modelo
miraba solo la forma reciente del bateador, como si todos los rivales
fueran iguales — y no lo son. Es la variable que más pesa en los props
de bateo, y los datos ya los tenemos de la MLB API.

Cómo funciona: se compara el WHIP del abridor rival contra el promedio
de la liga. Un pitcher que permite menos baserunners que la media baja
la probabilidad del bateador; uno que permite más, la sube.

Deliberadamente conservador. El ajuste máximo es de ±12%, porque:

- El abridor no cubre todo el partido. Un bateador con 4 turnos suele
  enfrentarlo 2 o 3 veces y el resto es bullpen.
- El WHIP resume mucho en un número: no distingue un pitcher que da
  muchas bases por bolas de uno al que le pegan.
- El mercado YA descontó quién lanza. La línea de un bateador contra un
  as ya viene ajustada, así que sobrecorregir generaría ventajas
  falsas — el problema que venimos arrastrando.
"""
from __future__ import annotations

from app.utils.logger import get_logger

log = get_logger(__name__)

# WHIP promedio de un abridor de MLB (baserunners permitidos por entrada).
# Sirve de referencia: por encima es peor que la media, por debajo mejor.
WHIP_LIGA = 1.28

# Tope del ajuste, hacia arriba o hacia abajo.
AJUSTE_MAXIMO = 0.12

# Sin un mínimo de entradas, el WHIP es ruido: un pitcher con dos
# aperturas puede tener 0.60 por casualidad.
_ENTRADAS_MINIMAS = 20.0


def factor_por_pitcher(whip_rival: float | None, entradas: float | None = None) -> float:
    """Multiplicador para la probabilidad de un bateador.

    >1 significa rival flojo (sube la chance del bateador), <1 rival
    duro. Devuelve 1.0 -sin efecto- cuando no hay datos suficientes:
    ante la duda no se toca la estimación.
    """
    if not whip_rival or whip_rival <= 0:
        return 1.0
    if entradas is not None and entradas < _ENTRADAS_MINIMAS:
        return 1.0

    # Diferencia relativa contra la liga. Un WHIP más alto que la media
    # favorece al bateador.
    diferencia = (whip_rival - WHIP_LIGA) / WHIP_LIGA

    # Se amortigua a la mitad antes de topear: el abridor no cubre todo
    # el partido y el mercado ya descontó parte de esto.
    ajuste = max(-AJUSTE_MAXIMO, min(AJUSTE_MAXIMO, diferencia * 0.5))
    return 1.0 + ajuste


def describir_matchup(whip_rival: float | None, nombre: str | None = None) -> str:
    """Texto corto para mostrar por qué se ajustó."""
    if not whip_rival:
        return ""
    quien = nombre or "el abridor rival"
    if whip_rival <= WHIP_LIGA - 0.15:
        return f"{quien} viene difícil (WHIP {whip_rival:.2f})"
    if whip_rival >= WHIP_LIGA + 0.15:
        return f"{quien} viene permisivo (WHIP {whip_rival:.2f})"
    return f"{quien}: WHIP {whip_rival:.2f}, en la media"


def aplicar(probabilidad_pct: float, whip_rival: float | None,
            entradas: float | None = None) -> float:
    """Aplica el ajuste sin salirse de un rango razonable."""
    factor = factor_por_pitcher(whip_rival, entradas)
    ajustada = probabilidad_pct * factor
    # Nunca llevar a 0 ni a 100: son afirmaciones que el dato no sostiene.
    return round(max(1.0, min(97.0, ajustada)), 1)
