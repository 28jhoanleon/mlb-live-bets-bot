"""Tests de análisis de combinada y tracking en vivo (solo la parte
matemática, sin red). Correr con: pytest tests/"""
from app.analysis.parlay import analyze_parlay
from app.analysis.probability import LegEstimate
from app.analysis.live_tracking import _remaining_fraction
from app.utils.progress_bar import _EMPTY, _FILLED, build_progress_bar


def _leg(player, pct, sample=10, avg=1.0, is_pitcher=False):
    return LegEstimate(
        player=player,
        market="Hits",
        side="Over",
        threshold=1.5,
        probability_pct=pct,
        sample_size=sample,
        avg_value=avg,
        is_pitcher=is_pitcher,
    )


def test_parlay_identifies_riskiest_leg():
    legs = [_leg("A", 70.0), _leg("B", 20.0), _leg("C", 60.0)]
    verdict = analyze_parlay(legs)
    assert verdict.riskiest_leg.player == "B"
    assert verdict.safest_leg.player == "A"


def test_parlay_combined_probability_is_product():
    legs = [_leg("A", 50.0), _leg("B", 50.0)]
    verdict = analyze_parlay(legs)
    assert verdict.combined_probability_pct == 25.0


def test_parlay_risk_label_high_combined():
    legs = [_leg("A", 90.0), _leg("B", 85.0)]
    verdict = analyze_parlay(legs)
    assert "🟢" in verdict.risk_label


def test_parlay_risk_label_low_combined():
    legs = [_leg("A", 15.0), _leg("B", 15.0)]
    verdict = analyze_parlay(legs)
    assert "🔴" in verdict.risk_label


def test_progress_bar_partial():
    # Objetivo de Over 6.5 es 7 -> 2/7 de 10 bloques = 3
    bar = build_progress_bar(2, 6.5, length=10)
    assert bar.count(_FILLED) == 3
    assert bar.count(_EMPTY) == 7


def test_progress_bar_completed_caps_at_full():
    bar = build_progress_bar(10, 6.5, length=10)
    # Cumplida -> barra llena y check en lugar del objetivo
    assert bar.count(_FILLED) == 10
    assert bar.endswith("✅")
    assert bar.endswith("✅")


def test_remaining_fraction_early_game():
    # Inning 1, top -> casi todo el partido por delante
    frac = _remaining_fraction(1, "Top")
    assert frac > 0.9


def test_remaining_fraction_late_game():
    # Inning 9, bottom -> ya casi no queda partido
    frac = _remaining_fraction(9, "Bottom")
    assert frac < 0.1


def test_remaining_fraction_no_data_defaults_to_half():
    assert _remaining_fraction(None, None) == 0.5
