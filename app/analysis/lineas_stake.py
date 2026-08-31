"""Líneas mínimas que Stake ofrece de verdad, por mercado.

Sugerir "Over 1.5" en un mercado donde la casa arranca en 8.5 (por
ejemplo, outs de un abridor) no es una sugerencia útil: es una línea
que casi nunca falla, tan floja que ninguna casa la ofrecería con una
cuota que valga la pena -- en la práctica, casi 1.00. Este archivo no
tiene dependencias de otros módulos de análisis, justamente para poder
usarse desde cualquiera sin crear ciclos de import.
"""

LINEA_MINIMA = {
    "pitcher_strikeouts": 1.5,
    "pitcher_hits_allowed": 2.5,
    "pitcher_earned_runs": 1.5,
    "pitcher_outs": 8.5,
    "pitcher_walks": 1.5,
}


def linea_jugable(market_key: str, punto: float | None) -> bool:
    """¿La casa ofrece de verdad una línea así de baja para este mercado?"""
    if punto is None:
        return True
    minimo = LINEA_MINIMA.get(market_key)
    return minimo is None or punto >= minimo
