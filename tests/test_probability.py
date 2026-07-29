"""Tests de la lógica de probabilidad que no depende de red (parseo de
líneas, clasificación de mercados). Correr con: pytest tests/"""
import pytest

from app.analysis.probability import (
    ProbabilityError,
    _classify_batter_market,
    _classify_pitcher_market,
    _parse_line,
)


def test_parse_line_over_english():
    assert _parse_line("Over 6.5") == ("Over", 6.5)


def test_parse_line_over_spanish():
    assert _parse_line("Más de 2.5") == ("Over", 2.5)


def test_parse_line_under():
    assert _parse_line("Under 14.5") == ("Under", 14.5)


def test_parse_line_menos_spanish():
    assert _parse_line("Menos de 3.5") == ("Under", 3.5)


def test_parse_line_invalid_raises():
    with pytest.raises(ProbabilityError):
        _parse_line("no es una línea")


def test_classify_batter_combined_hrr():
    assert _classify_batter_market("Hits + Runs + RBIs") == ["hits", "runs", "rbi"]


def test_classify_batter_home_runs():
    assert _classify_batter_market("Home Runs") == ["home_runs"]


def test_classify_batter_own_strikeouts():
    """El propio bateador ponchándose (Batter Strikeouts) -> distinto de
    los ponches que reparte un pitcher."""
    assert _classify_batter_market("Batter Strikeouts") == ["strikeouts"]


def test_classify_batter_hits():
    assert _classify_batter_market("Hits") == ["hits"]


def test_classify_pitcher_strikeouts():
    assert _classify_pitcher_market("Strikeouts") == ["strikeouts"]


def test_classify_pitcher_outs():
    assert _classify_pitcher_market("Outs") == ["outs"]


def test_classify_unknown_market_raises():
    with pytest.raises(ProbabilityError):
        _classify_batter_market("mercado inventado que no existe")
