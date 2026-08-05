"""Tres bugs que aparecieron en los logs de producción y que ningún test
cubría. Juntos hacían que /mejorar quedara colgado para siempre en
"Revisando tus tramos...": el comando crasheaba y, como no hay un
manejador de errores global, el mensaje nunca se editaba.
"""
from unittest.mock import patch

import pytest

from app.mlb import pitchers, players


class TestStatsVacio:
    """IndexError: list index out of range en get_recent_pitching_games.

    La MLB API devuelve {"stats": []} -lista VACÍA- cuando el jugador no
    tiene partidos en esa categoría (un pitcher recién subido, o un
    bateador al que se le pide gameLog de pitcheo). El default [{}] no
    cubre ese caso y el índice [0] reventaba."""

    def test_pitching_con_stats_vacio_no_revienta(self):
        with patch.object(pitchers, "get", return_value={"stats": []}):
            assert pitchers.get_recent_pitching_games(123) == []

    def test_hitting_con_stats_vacio_no_revienta(self):
        with patch.object(players, "get", return_value={"stats": []}):
            assert players.get_recent_hitting_games(123) == []

    def test_sin_la_clave_stats_tampoco_revienta(self):
        with patch.object(pitchers, "get", return_value={}):
            assert pitchers.get_recent_pitching_games(123) == []

    def test_con_datos_reales_sigue_andando(self):
        payload = {"stats": [{"splits": [
            {"date": "2026-08-01", "stat": {"strikeOuts": 8, "outs": 18}},
        ]}]}
        with patch.object(pitchers, "get", return_value=payload):
            juegos = pitchers.get_recent_pitching_games(123)
        assert len(juegos) == 1
        assert juegos[0]["strikeouts"] == 8


class TestCuotaDeLaOddsApi:
    """El log mostró "Quedan solo -13 consultas": el barrido pedía 12
    partidos sin mirar cuánta cuota quedaba y la dejaba en negativo."""

    def setup_method(self):
        from app.odds import theodds
        theodds._cuota_restante = None

    def test_sin_cuota_no_se_piden_partidos(self):
        from app.odds import theodds
        theodds._cuota_restante = 5
        assert theodds.partidos_que_alcanzan(12) == 0

    def test_con_cuota_justa_se_piden_menos(self):
        from app.odds import theodds
        theodds._cuota_restante = 14  # 14 - 10 de reserva = 4
        assert theodds.partidos_que_alcanzan(12) == 4

    def test_con_cuota_de_sobra_se_piden_todos(self):
        from app.odds import theodds
        theodds._cuota_restante = 500
        assert theodds.partidos_que_alcanzan(12) == 12

    def test_si_no_sabemos_la_cuota_se_confia(self):
        from app.odds import theodds
        theodds._cuota_restante = None
        assert theodds.partidos_que_alcanzan(12) == 12

    def test_barrido_sin_cuota_devuelve_vacio_sin_pegarle_a_la_api(self):
        from app.analysis import daily_picks
        from app.odds import theodds

        theodds._cuota_restante = 2
        with patch("app.odds.theodds.get_events",
                   return_value=[{"id": str(i), "away_team": "A", "home_team": "B",
                                  "commence_time": "2099-01-01T00:00:00Z"}
                                 for i in range(12)]), \
             patch("app.odds.theodds.get_player_props") as props, \
             patch.object(daily_picks, "evento_vigente", return_value=True):
            assert daily_picks.find_daily_picks() == []
        assert not props.called, "gastó cuota aunque no quedaba"


class TestFirmaDelHelper:
    """TypeError: edit_then_send_rest() got multiple values for argument
    'parse_mode'. El handler le pasaba `update` de más."""

    def test_la_llamada_de_mejorar_coincide_con_la_firma(self):
        import inspect

        from app.utils.telegram_helpers import edit_then_send_rest

        parametros = list(inspect.signature(edit_then_send_rest).parameters)
        assert parametros == ["processing_msg", "text", "parse_mode"]

    def test_mejorar_no_pasa_update_al_helper(self):
        import pathlib

        fuente = pathlib.Path("app/bot/handlers/mejorar.py").read_text()
        assert "edit_then_send_rest(aviso, update" not in fuente, (
            "vuelve a pasarle `update` al helper: eso crashea el comando "
            "y deja el mensaje colgado en 'Revisando...'"
        )
