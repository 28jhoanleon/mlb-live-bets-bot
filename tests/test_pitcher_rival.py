"""Ajuste por el pitcher rival.

Que un bateador promedie 1.2 hits no dice nada solo: ese promedio sale
de enfrentar abridores cualquiera. Contra un as su chance real baja;
contra uno castigado, sube. Es la variable que más pesa en props de
bateo y el bot la ignoraba por completo.
"""
from unittest.mock import patch

from app.analysis import pitcher_rival as pr
from app.analysis.pitcher_rival import (
    AJUSTE_MAXIMO,
    AJUSTE_MINIMO,
    WHIP_LIGA,
    _innings_a_float,
    factor_por_pitcher_rival,
)


class TestInningsDeLaMlbApi:
    def test_interpreta_los_tercios(self):
        """La MLB informa "45.2" como 45 entradas y 2 outs, NO 45.2
        decimal. Tomarlo como decimal distorsiona todo el WHIP."""
        assert abs(_innings_a_float("45.2") - 45.667) < 0.01
        assert _innings_a_float("45.0") == 45.0

    def test_valor_invalido_da_cero(self):
        assert _innings_a_float(None) == 0.0
        assert _innings_a_float("x") == 0.0


class TestFactor:
    def _con_whip(self, whip):
        pr.limpiar_cache_pitchers()
        with patch.object(pr, "whip_del_pitcher", return_value=whip):
            return factor_por_pitcher_rival("Cualquiera")

    def test_un_as_baja_la_probabilidad(self):
        assert self._con_whip(0.95) < 1.0

    def test_un_pitcher_castigado_la_sube(self):
        assert self._con_whip(1.60) > 1.0

    def test_un_pitcher_promedio_no_cambia_nada(self):
        assert self._con_whip(WHIP_LIGA) == 1.0

    def test_el_ajuste_esta_acotado(self):
        """Sin tope, un WHIP extremo por muestra chica daría
        correcciones absurdas. El WHIP solo no tiene esa precisión."""
        assert self._con_whip(0.30) >= AJUSTE_MINIMO
        assert self._con_whip(3.00) <= AJUSTE_MAXIMO


class TestNoInventaCuandoFaltaElDato:
    def test_sin_pitcher_no_ajusta(self):
        assert factor_por_pitcher_rival(None) == 1.0
        assert factor_por_pitcher_rival("") == 1.0

    def test_sin_whip_no_ajusta(self):
        pr.limpiar_cache_pitchers()
        with patch.object(pr, "whip_del_pitcher", return_value=None):
            assert factor_por_pitcher_rival("Desconocido") == 1.0

    def test_pocas_entradas_no_cuentan(self):
        """Con 10 entradas un WHIP de 0.60 es ruido, no dominio."""
        pr.limpiar_cache_pitchers()
        with patch.object(pr, "search_player",
                          return_value={"id": 1, "full_name": "Novato"}), \
             patch.object(pr, "get_season_pitching_stats",
                          return_value={"inningsPitched": "10.0", "hits": 4,
                                        "baseOnBalls": 2}):
            assert pr.whip_del_pitcher("Novato") is None

    def test_si_la_api_falla_no_rompe(self):
        pr.limpiar_cache_pitchers()
        with patch.object(pr, "search_player", side_effect=ConnectionError("cortó")):
            assert pr.whip_del_pitcher("X") is None


class TestNoSeAplicaAMercadosDePitcheo:
    def test_el_codigo_excluye_los_mercados_de_pitcher(self):
        """Un prop sobre lo que hace el propio lanzador no depende de
        quién lanza enfrente."""
        import pathlib

        fuente = pathlib.Path("app/analysis/daily_picks.py").read_text()
        assert 'if not market_label.startswith("pitcher_"):' in fuente
