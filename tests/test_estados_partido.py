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

    def test_encuentra_partido_de_dos_dias_atras(self):
        """Un ticket resuelto hace más de un día tiene que seguir
        encontrando su partido: 'ayer' nada más no alcanzaba."""
        from datetime import date

        def _schedule_por_dia(target_date=None):
            if target_date == date(2026, 7, 28):  # hace 2 días
                return _schedule("Final")
            return []  # hoy y ayer, nada

        with patch("app.mlb.live.hoy_local", return_value=date(2026, 7, 30)), \
             patch("app.mlb.live.get_schedule", side_effect=_schedule_por_dia), \
             patch("app.mlb.live.get_live_game", return_value=_live_feed()):
            assert find_live_game_by_teams("phillies", "marlins") == 777

    def test_partido_de_hoy_sin_arrancar_le_gana_al_final_de_ayer(self):
        """EL bug real reportado, y el que ningún test agarraba: Stake
        mostraba Rangers @ Rays arrancando en 59 minutos, y la web lo
        mostraba FINAL 0-3 con las legs ya resueltas -- los datos del
        MISMO cruce jugado AYER.

        La causa era el ORDEN: se filtraba por "tiene datos" ANTES de
        elegir el más cercano a ahora. El partido de hoy, todavía
        'Scheduled', quedaba fuera del pool de candidatos, así que el
        Final de ayer ganaba por no tener con quién competir.

        Lo correcto: elegir primero el partido más cercano sobre TODO el
        calendario y recién después mirar si tiene datos. Si el más
        cercano no arrancó, no hay datos en vivo -> None -> histórico."""
        from datetime import date

        hoy_sin_arrancar = {
            "game_pk": 222, "status": "Scheduled",
            "away_team": "Texas Rangers", "home_team": "Tampa Bay Rays",
            "game_time_utc": "2026-07-30T17:10:00Z",  # arranca en un rato
        }
        ayer_terminado = {
            "game_pk": 111, "status": "Final",
            "away_team": "Texas Rangers", "home_team": "Tampa Bay Rays",
            "game_time_utc": "2026-07-29T17:10:00Z",  # el de ayer
        }

        def _schedule_por_dia(target_date=None):
            if target_date == date(2026, 7, 30):
                return [hoy_sin_arrancar]
            if target_date == date(2026, 7, 29):
                return [ayer_terminado]
            return []

        with patch("app.mlb.live.hoy_local", return_value=date(2026, 7, 30)), \
             patch("app.mlb.live.get_schedule", side_effect=_schedule_por_dia), \
             patch("app.mlb.live.get_live_game", return_value=_live_feed()):
            resultado = find_live_game_by_teams("texas rangers", "tampa bay rays")

        assert resultado != 111, (
            "devolvió el game_pk del partido de AYER (ya Final) para un "
            "partido de hoy que todavía no arrancó -- la web va a mostrar "
            "el resultado de ayer como si fuera el de hoy"
        )
        assert resultado is None, (
            "el partido de hoy todavía no arrancó: no hay datos en vivo, "
            "tiene que caer al histórico"
        )

    def test_serie_de_varios_dias_elige_el_final_mas_reciente(self):
        """Si los mismos dos equipos jugaron Final hace 3 días Y hace 1
        día (serie), tiene que quedarse con el más cercano a ahora, no
        con cualquiera."""
        from datetime import date, datetime, timezone
        from unittest.mock import patch as _patch

        def _schedule_por_dia(target_date=None):
            if target_date == date(2026, 7, 27):  # hace 3 dias
                return [{**_schedule("Final")[0], "game_pk": 111,
                          "game_time_utc": "2026-07-27T17:10:00Z"}]
            if target_date == date(2026, 7, 29):  # ayer
                return [{**_schedule("Final")[0], "game_pk": 999,
                          "game_time_utc": "2026-07-29T17:10:00Z"}]
            return []

        with patch("app.mlb.live.hoy_local", return_value=date(2026, 7, 30)), \
             patch("app.mlb.live.get_schedule", side_effect=_schedule_por_dia), \
             patch("app.mlb.live.get_live_game", return_value=_live_feed()), \
             _patch("app.mlb.estados.datetime") as dt_mock:
            dt_mock.now.return_value = datetime.fromisoformat("2026-07-29T20:00:00+00:00")
            dt_mock.fromisoformat.side_effect = datetime.fromisoformat
            assert find_live_game_by_teams("phillies", "marlins") == 999


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
