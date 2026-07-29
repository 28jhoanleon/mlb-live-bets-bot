"""Tests de la capa web.

Lo importante: la web y el bot tienen que mostrar lo MISMO. Si divergen,
tenemos dos verdades y el proyecto se vuelve inmantenible. Por eso el
servicio web reusa la misma lógica de tickets y tracking.
"""
from unittest.mock import patch

import pytest

from app.utils.market_labels import nombre_stake


BOXSCORE = {
    "George Kirby": {
        "player_id": 1,
        "is_team_last_pitcher": False,
        "is_current_pitcher": False,
        "batting_order": None,
        "batting": {},
        "pitching": {"strikeouts": 3, "outs": 18, "walks": 1, "hits_allowed": 7},
    },
    "Ezequiel Duran": {
        "player_id": 3,
        "is_team_last_pitcher": False,
        "is_current_batter": False,
        "batting_order": "400",
        "is_on_bench": False,
        "batting": {
            "hits": 2, "runs": 1, "rbi": 1, "home_runs": 0,
            "strikeouts": 1, "walks": 0, "stolen_bases": 0,
        },
        "pitching": {},
    },
}

LIVE_STATE = {
    "inning": 7, "inning_state": "Bottom", "current_pitcher": "Otro",
    "away_team": "Texas Rangers", "home_team": "Seattle Mariners",
    "away_score": 7, "home_score": 2, "status": "In Progress",
}

APUESTA = {
    "is_live": True,
    "bets": [{
        "match": "Texas Rangers @ Seattle Mariners",
        "total_odds": "5.60",
        "is_live": True,
        "legs": [
            {"match": "Texas Rangers @ Seattle Mariners", "player": "George Kirby",
             "market": "Strikeouts", "line": "Over 3.5", "odds": None},
            {"match": "Texas Rangers @ Seattle Mariners", "player": "Ezequiel Duran",
             "market": "Hits + Runs + RBIs", "line": "Over 1.5", "odds": None},
        ],
    }],
}


def _buscar_jugador(nombre):
    if "Duran" in nombre:
        return {"id": 3, "full_name": "Ezequiel Duran", "position": "Infielder"}
    return {"id": 1, "full_name": nombre, "position": "Pitcher"}


@pytest.fixture
def estado(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/web.db")
    from app.db import database

    monkeypatch.setattr(database, "_db_path", lambda: str(tmp_path / "web.db"))
    database.init_db()
    database.save_active_bet(999, APUESTA)

    from app.web.service import estado_apuestas

    partido = {
        "game_pk": 1,
        "status": "In Progress",
        "away_team": "Texas Rangers",
        "home_team": "Seattle Mariners",
        "game_time_utc": "2026-07-29T18:10:00Z",
    }

    with patch("app.web.service.buscar_partido", return_value=partido), \
         patch("app.web.service.get_live_tracking_for_match", return_value=(BOXSCORE, LIVE_STATE)), \
         patch("app.analysis.live_tracking.search_player", side_effect=_buscar_jugador), \
         patch("app.analysis.live_tracking._recent_avg_rate", return_value=1.2):
        return estado_apuestas(999)


class TestEstadoParaLaWeb:
    def test_devuelve_los_tickets(self, estado):
        assert estado["count"] == 1
        assert len(estado["tickets"][0]["legs"]) == 2

    def test_usa_nombres_cortos_de_equipo(self, estado):
        assert estado["tickets"][0]["match"] == "Rangers @ Mariners"

    def test_incluye_marcador_y_entrada(self, estado):
        t = estado["tickets"][0]
        assert t["away_score"] == 7
        assert t["inning"] == 7
        assert t["inning_state"] == "abajo"

    def test_cuenta_las_cumplidas(self, estado):
        assert estado["tickets"][0]["done"] == 1
        assert estado["tickets"][0]["total"] == 2

    def test_pitcher_que_salio_queda_en_dead(self, estado):
        kirby = estado["tickets"][0]["legs"][0]
        assert kirby["state"] == "dead"
        assert kirby["pct"] == 75.0  # 3 de 4

    def test_leg_cumplida_llega_al_100(self, estado):
        duran = estado["tickets"][0]["legs"][1]
        assert duran["state"] == "done"
        assert duran["pct"] == 100.0

    def test_el_porcentaje_nunca_se_pasa_de_100(self, estado):
        for leg in estado["tickets"][0]["legs"]:
            assert 0 <= leg["pct"] <= 100


class TestNombreDeMercado:
    """La web muestra el mercado tal como hay que buscarlo en Stake."""

    def test_traduce_claves_de_la_api_de_odds(self):
        assert nombre_stake("batter_hits_runs_rbis") == "Golpes + Carreras + Carreras Remolcadas"

    def test_no_arruina_nombres_ya_legibles(self):
        """El bug: '.title()' convertía 'RBIs' en 'Rbis'."""
        assert nombre_stake("Hits + Runs + RBIs") == "Hits + Runs + RBIs"

    def test_deja_intacto_el_espanol_de_la_captura(self):
        assert nombre_stake("Golpes Permitidos") == "Golpes Permitidos"


class TestApi:
    def test_health_responde(self):
        from starlette.testclient import TestClient

        from app.web.api import app

        assert TestClient(app).get("/health").json() == {"ok": True}

    def test_rechaza_clave_incorrecta(self, monkeypatch):
        from starlette.testclient import TestClient

        from app.web.api import app

        monkeypatch.setenv("WEB_KEY", "secreta")
        r = TestClient(app).get("/api/bets?k=equivocada")
        assert r.status_code == 401

    def test_avisa_si_falta_el_chat_id(self, monkeypatch):
        from starlette.testclient import TestClient

        from app.web.api import app

        monkeypatch.setenv("WEB_KEY", "")
        monkeypatch.setenv("OWNER_CHAT_ID", "")
        r = TestClient(app).get("/api/bets")
        assert r.status_code == 500
        assert "OWNER_CHAT_ID" in r.json()["detail"]


class TestDeteccionAutomaticaDeEnVivo:
    """Bug: el servicio solo buscaba datos en vivo si la captura YA decía
    'En vivo'. Una apuesta cargada antes del primer lanzamiento quedaba
    marcada como no-live para siempre y nunca cambiaba sola."""

    def _guardar(self, tmp_path, monkeypatch, is_live: bool):
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/w.db")
        from app.db import database

        monkeypatch.setattr(database, "_db_path", lambda: str(tmp_path / "w.db"))
        database.init_db()
        database.save_active_bet(
            5,
            {
                "is_live": is_live,
                "bets": [{
                    "match": "Detroit Tigers @ Baltimore Orioles",
                    "total_odds": "1.86",
                    "is_live": is_live,
                    "legs": [{
                        "match": "Detroit Tigers @ Baltimore Orioles",
                        "player": "Kevin McGonigle",
                        "market": "Hits + Runs + RBIs",
                        "line": "Over 0.5",
                    }],
                }],
            },
        )

    def _partido(self, status):
        return {
            "game_pk": 1, "status": status,
            "away_team": "Detroit Tigers", "home_team": "Baltimore Orioles",
            "game_time_utc": "2026-07-29T18:10:00Z",
        }

    def test_pasa_a_en_vivo_aunque_la_captura_dijera_que_no(self, tmp_path, monkeypatch):
        self._guardar(tmp_path, monkeypatch, is_live=False)
        from app.web.service import estado_apuestas

        with patch("app.web.service.buscar_partido", return_value=self._partido("In Progress")), \
             patch("app.web.service.get_live_tracking_for_match", return_value=(BOXSCORE, LIVE_STATE)):
            estado = estado_apuestas(5)

        assert estado["tickets"][0]["live"] is True

    def test_no_pide_datos_en_vivo_si_no_empezo(self, tmp_path, monkeypatch):
        """No malgastamos llamadas a la API con partidos que no arrancaron."""
        self._guardar(tmp_path, monkeypatch, is_live=True)
        from app.web.service import estado_apuestas

        with patch("app.web.service.buscar_partido", return_value=self._partido("Scheduled")), \
             patch("app.web.service.get_live_tracking_for_match") as mock_live, \
             patch("app.web.service.estimate_leg_probability", side_effect=Exception("sin datos")):
            estado_apuestas(5)

        mock_live.assert_not_called()


class TestLogosYHorario:
    def test_devuelve_los_logos_de_ambos_equipos(self):
        from app.utils.equipos import logo_equipo

        assert logo_equipo("Detroit Tigers").endswith("/116.svg")
        assert logo_equipo("Baltimore Orioles").endswith("/110.svg")

    def test_reconoce_el_apodo(self):
        from app.utils.equipos import logo_equipo

        assert logo_equipo("Tigers") == logo_equipo("Detroit Tigers")

    def test_equipo_desconocido_no_rompe(self):
        """Preferimos no mostrar escudo antes que romper la página."""
        from app.utils.equipos import logo_equipo

        assert logo_equipo("Equipo Inventado FC") is None
        assert logo_equipo(None) is None


class TestCacheDelCalendario:
    """La web consulta cada 30s: sin caché serían llamadas idénticas
    repetidas a la MLB Stats API por cada ticket."""

    def test_reutiliza_el_resultado(self):
        from app.mlb import schedule

        schedule.limpiar_cache()
        with patch("app.mlb.schedule.get_schedule", return_value=[{"game_pk": 1}]) as mock:
            schedule.get_schedule_cacheado()
            schedule.get_schedule_cacheado()
            schedule.get_schedule_cacheado()

        assert mock.call_count == 1

    def test_limpiar_cache_fuerza_recarga(self):
        from app.mlb import schedule

        schedule.limpiar_cache()
        with patch("app.mlb.schedule.get_schedule", return_value=[{"game_pk": 1}]) as mock:
            schedule.get_schedule_cacheado()
            schedule.limpiar_cache()
            schedule.get_schedule_cacheado()

        assert mock.call_count == 2
