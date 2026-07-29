"""Análisis de combinadas: junta las probabilidades individuales de cada
leg (ya estimadas empíricamente) y da un veredicto sobre el conjunto.

Importante sobre la probabilidad combinada: multiplicar las probabilidades
individuales asume independencia entre legs. Si son del MISMO partido
(Same Game Multi), en la realidad suelen estar correlacionadas (si tu
equipo gana cómodo, es más probable que varios bateadores conecten hits
a la vez) — así que la probabilidad "real" combinada probablemente sea
ALGO más alta que la simple multiplicación. Avisamos ese matiz en vez de
fingir precisión que no tenemos.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.analysis.probability import LegEstimate


@dataclass
class ParlayVerdict:
    combined_probability_pct: float
    same_game: bool
    riskiest_leg: LegEstimate
    safest_leg: LegEstimate
    risk_label: str
    recommendation: str


def _risk_label(combined_pct: float, n_legs: int) -> str:
    if combined_pct >= 40:
        return "🟢 Riesgo moderado"
    if combined_pct >= 20:
        return "🟡 Riesgo alto"
    return "🔴 Riesgo muy alto"


def analyze_parlay(legs: list[LegEstimate], same_game: bool = True) -> ParlayVerdict:
    if not legs:
        raise ValueError("No hay legs para analizar.")

    combined = 1.0
    for leg in legs:
        combined *= leg.probability_pct / 100
    combined_pct = round(combined * 100, 1)

    sorted_legs = sorted(legs, key=lambda l: l.probability_pct)
    riskiest = sorted_legs[0]
    safest = sorted_legs[-1]

    risk_label = _risk_label(combined_pct, len(legs))

    if riskiest.probability_pct < 25:
        recommendation = (
            f"⚠️ La leg de {riskiest.player} ({riskiest.market}) es el punto débil: "
            f"solo se cumplió en {riskiest.probability_pct}% de sus últimos "
            f"{riskiest.sample_size} partidos. Esa leg sola le baja el valor a toda la combinada."
        )
    elif combined_pct < 15:
        recommendation = (
            "⚠️ La probabilidad combinada es baja. No hay ninguna leg individualmente mala, "
            "pero juntar varias legs de riesgo medio multiplica el riesgo total."
        )
    else:
        recommendation = "✅ Las legs tienen forma reciente sólida. Combinada razonable dentro de su riesgo."

    return ParlayVerdict(
        combined_probability_pct=combined_pct,
        same_game=same_game,
        riskiest_leg=riskiest,
        safest_leg=safest,
        risk_label=risk_label,
        recommendation=recommendation,
    )
