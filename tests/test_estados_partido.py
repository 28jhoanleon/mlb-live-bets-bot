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
para ejercitar el camino real.

Ojo: el primer arreglo de este bug metió una regresión (mezclar
`get_live_games_today`, la que usa /live, con los estados terminados).
Por eso hay tests separados para las dos funciones."""
from unittest.mock import patch

from app.mlb.live import find_live_game_by_teams, get_live_games_today


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
    """find_live_game_by_teams: la usa el tracking de legs, tiene que
    encontrar el partido esté en curso o ya haya terminado."""

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


class TestLiveCommandNoListaTerminados:
    """get_live_games_today la usa /live: tiene que seguir mostrando
    SOLO partidos en curso. Mezclarla con los terminados (como pasó en
    el primer intento de arreglo) haría que /live liste partidos ya
    terminados como si estuvieran en curso."""

    def test_final_no_aparece_en_live_games_today(self):
        with patch("app.mlb.live.get_schedule", return_value=_schedule("Final")), \
             patch("app.mlb.live.get_live_game", return_value=_live_feed()):
            assert get_live_games_today() == []

    def test_in_progress_si_aparece_en_live_games_today(self):
        with patch("app.mlb.live.get_schedule", return_value=_schedule("In Progress")), \
             patch("app.mlb.live.get_live_game", return_value=_live_feed()):
            juegos = get_live_games_today()
            assert len(juegos) == 1
            assert juegos[0]["game_pk"] == 777
