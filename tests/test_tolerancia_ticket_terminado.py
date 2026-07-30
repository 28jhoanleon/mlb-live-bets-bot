"""Tolerancia antes de sacar un ticket terminado de la lista: se
muestra colapsado un rato después de terminar (para poder revisarlo) y
recién después de TOLERANCIA_TICKET_TERMINADO desaparece del todo."""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest


BOXSCORE_FINAL = {
    "Kyle Schwarber": {
        "player_id": 1,
        "is_current_batter": False,
        "batting_order": "3",
        "is_on_bench": False,
        "batting": {"hits": 2, "runs": 1, "rbi": 1, "home_runs": 0, "strikeouts": 0, "walks": 0, "stolen_bases": 0},
        "pitching": {},
    },
}

LIVE_STATE_FINAL = {
    "inning": 9, "inning_state": "End", "current_pitcher": None,
    "away_team": "Philadelphia Phillies", "home_team": "Miami Marlins",
    "away_score": 8, "home_score": 6, "status": "Final",
}

PARTIDO = {
    "game_pk": 1, "status": "Final",
    "away_team": "Philadelphia Phillies", "home_team": "Miami Marlins",
    "game_time_utc": "2026-07-29T17:10:00Z",
}

APUESTA = {
    "is_live": False,
    "bets": [{
        "match": "Philadelphia Phillies @ Miami Marlins",
        "total_odds": "1.90",
        "is_live": False,
        "legs": [
            {"match": "Philadelphia Phillies @ Miami Marlins", "player": "Kyle Schwarber",
             "market": "Hits + Runs + RBIs", "line": "Over 0.5", "odds": None},
        ],
    }],
}


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/web.db")
    from app.db import database

    monkeypatch.setattr(database, "_db_path", lambda: str(tmp_path / "web.db"))
    database.init_db()
    database.save_active_bet(999, APUESTA)
    return database


def _calcular_estado():
    from app.web.service import estado_apuestas

    with patch("app.web.service.buscar_partido", return_value=PARTIDO), \
         patch("app.web.service.get_live_tracking_for_match",
               return_value=(BOXSCORE_FINAL, LIVE_STATE_FINAL)), \
         patch("app.analysis.live_tracking.search_player",
               return_value={"id": 1, "full_name": "Kyle Schwarber", "position": "Hitter"}):
        return estado_apuestas(999)


class TestToleranciaTicketTerminado:
    def test_recien_terminado_todavia_se_muestra(self, db):
        estado = _calcular_estado()
        assert estado["count"] == 1
        assert estado["tickets"][0]["terminado"] is True

    def test_pasada_la_tolerancia_desaparece(self, db):
        # Primera vez: lo marca terminado ahora mismo.
        _calcular_estado()

        # Simulamos que eso pasó hace mucho, pisando el timestamp guardado.
        hace_rato = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
        with db._connection() as conn:
            conn.execute(
                "UPDATE ticket_terminado SET terminado_desde = ? WHERE chat_id = ?",
                (hace_rato, "999"),
            )

        estado = _calcular_estado()
        assert estado["count"] == 0, "el ticket debería haber desaparecido tras la tolerancia"
