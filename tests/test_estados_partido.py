"""Bug real (reportado en producción, no lo agarró ningún test): un
partido con status FINAL nunca encontraba su game_pk en
find_live_game_by_teams, así que la web siempre caía al promedio
histórico para partidos terminados aunque service.py sí sabía que un
Final "tiene datos".

La causa: dos listas de estados desincronizadas en dos archivos
distintos (app/mlb/live.py y app/web/service.py). Los tests anteriores
mockeaban directamente `get_live_tracking_for_match`, un nivel por
encima de donde estaba el bug, así que nunca lo iban a encontrar.
Estos tests mockean solo la capa de red (get_schedule / get_live_game)
para ejercitar el camino real."""
from unittest.mock import patch

from app.mlb.live import find_live_game_by_teams


def _schedule(status: str):
    return [
        {
            "game_pk": 777,
            "status": status,
            "away_team": "Philadelphia Phillies",
            "home_team": "Miami Marlins",
            "venue": "loanDepot park",
            "game_time_utc": "2026-07-29T17:10:00Z",
        }
    ]


def _live_feed():
    return {
        "inning": 9,
        "inning_state": "End",
        "away_score": 8,
        "home_score": 6,
        "current_pitcher": None,
        "bases": {},
    }


class TestPartidoTerminadoEncuentraGamePk:
    def test_final_encuentra_game_pk(self):
        with patch("app.mlb.live.get_schedule", return_value=_schedule("Final")), \
             patch("app.mlb.live.get_live_game", return_value=_live_feed()):
            assert find_live_game_by_teams("phillies", "marlins") == 777

    def test_game_over_encuentra_game_pk(self):
        with patch("app.mlb.live.get_schedule", return_value=_schedule("Game Over")), \
             patch("app.mlb.live.get_live_game", return_value=_live_feed()):
            assert find_live_game_by_teams("phillies", "marlins") == 777

    def test_scheduled_no_encuentra_nada(self):
        """Un partido que todavía no arrancó no tiene datos que buscar."""
        with patch("app.mlb.live.get_schedule", return_value=_schedule("Scheduled")), \
             patch("app.mlb.live.get_live_game", return_value=_live_feed()):
            assert find_live_game_by_teams("phillies", "marlins") is None

    def test_in_progress_sigue_encontrando(self):
        """No romper el caso que ya andaba: partido en curso."""
        with patch("app.mlb.live.get_schedule", return_value=_schedule("In Progress")), \
             patch("app.mlb.live.get_live_game", return_value=_live_feed()):
            assert find_live_game_by_teams("phillies", "marlins") == 777
