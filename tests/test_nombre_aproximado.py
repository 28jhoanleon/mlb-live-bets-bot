"""Caso real: la visión leyó "Chase Meldroth" (con L) de la captura,
pero el jugador es "Chase Meidroth" (con i). Una sola letra de
diferencia dejaba la leg sin datos en vivo.

El aviso de "no lo encuentro en el roster" funcionó como se esperaba
-avisó en vez de mostrar el histórico de otro-, pero un error de una
letra debería resolverlo el código, no el usuario."""
from unittest.mock import patch

from app.analysis.live_tracking import track_leg_live

LIVE_STATE = {"inning": 3, "inning_state": "Bottom", "status": "In Progress"}


def _box(nombre_real: str):
    return {
        nombre_real: {
            "player_id": 1, "is_current_batter": False, "batting_order": "1",
            "is_on_bench": False,
            "batting": {"hits": 0, "runs": 0, "rbi": 0, "walks": 1},
            "pitching": {},
        },
        "Munetaka Murakami": {
            "player_id": 2, "is_current_batter": False, "batting_order": "2",
            "is_on_bench": False,
            "batting": {"hits": 1, "runs": 0, "rbi": 0}, "pitching": {},
        },
    }


def _track(nombre_en_la_leg: str, nombre_real: str):
    with patch(
        "app.analysis.live_tracking.search_player",
        return_value={"id": 1, "full_name": nombre_real, "position": "Hitter"},
    ), patch("app.analysis.live_tracking._recent_avg_rate", return_value=1.2):
        return track_leg_live(
            {"player": nombre_en_la_leg, "market": "Hits + Runs + RBIs", "line": "Over 0.5"},
            _box(nombre_real),
            LIVE_STATE,
        )


class TestNombreConErrorDeTipeo:
    def test_meldroth_encuentra_a_meidroth(self):
        """El caso exacto reportado: una letra cambiada."""
        status = _track("Chase Meldroth", "Chase Meidroth")
        assert status.player == "Chase Meidroth"

    def test_nombre_exacto_sigue_andando(self):
        status = _track("Chase Meidroth", "Chase Meidroth")
        assert status.player == "Chase Meidroth"

    def test_no_confunde_dos_jugadores_distintos(self):
        """Lo importante del umbral alto: un nombre que NO está en el
        roster no debe engancharse al que más se le parezca. Mostrar las
        estadísticas de otro jugador es peor que avisar que no está."""
        import pytest

        from app.analysis.probability import ProbabilityError

        with pytest.raises(ProbabilityError):
            _track("Aaron Judge", "Chase Meidroth")
