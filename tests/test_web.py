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


class TestJugadorNoEnElRoster:
    """Bug real: 'Luis Rengifo' apareció bajo un partido en vivo cuyo
    roster no lo incluye (nombre real, pero de otro equipo -- típico de
    un error de lectura de la IA). Antes eso caía silenciosamente al
    promedio histórico de ese jugador, mostrándolo como si fuera dato
    relevante para ESE partido. Ahora debe avisar en vez de disfrazarlo
    de estadística en vivo."""

    def test_avisa_en_vez_de_mostrar_historico_disfrazado(self):
        from app.web.service import _leg_en_vivo

        leg = {
            "match": "Milwaukee Brewers @ San Francisco Giants",
            "player": "Luis Rengifo",
            "market": "Hits",
            "line": "Over 0.5",
            "odds": None,
        }
        resultado = _leg_en_vivo(leg, BOXSCORE, LIVE_STATE)

        assert resultado is not None
        assert resultado["state"] == "warn"
        assert resultado["live"] is True
        assert "roster" in resultado["note"]


class TestEstadoParaLaWeb:
    def _t(self, estado):
        return estado["tickets"][0]

    def _g(self, estado):
        return self._t(estado)["grupos"][0]

    def test_devuelve_la_apuesta(self, estado):
        assert estado["count"] == 1
        assert self._t(estado)["total"] == 2

    def test_agrupa_las_legs_por_partido(self, estado):
        grupos = self._t(estado)["grupos"]
        assert len(grupos) == 1
        assert len(grupos[0]["legs"]) == 2

    def test_usa_nombres_cortos_de_equipo(self, estado):
        assert self._g(estado)["match"] == "Rangers @ Mariners"

    def test_incluye_marcador_y_entrada_en_el_grupo(self, estado):
        g = self._g(estado)
        assert g["away_score"] == 7
        assert g["inning"] == 7
        assert g["inning_state"] == "abajo"

    def test_cuenta_las_cumplidas(self, estado):
        assert self._t(estado)["done"] == 1
        assert self._t(estado)["total"] == 2

    def test_pitcher_que_salio_queda_en_dead(self, estado):
        kirby = self._g(estado)["legs"][0]
        assert kirby["state"] == "dead"
        assert kirby["pct"] == 75.0  # 3 de 4

    def test_leg_cumplida_llega_al_100(self, estado):
        duran = self._g(estado)["legs"][1]
        assert duran["state"] == "done"
        assert duran["pct"] == 100.0

    def test_el_porcentaje_nunca_se_pasa_de_100(self, estado):
        for leg in self._g(estado)["legs"]:
            assert 0 <= leg["pct"] <= 100


class TestCombinadaDeVariosPartidos:
    """El bug: una combinada de 11 tramos repartidos en 5 juegos buscaba
    UN solo partido y aplicaba ese resultado a todas las legs. Las de los
    otros 4 juegos nunca recibían datos en vivo."""

    def _guardar(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/m.db")
        from app.db import database

        monkeypatch.setattr(database, "_db_path", lambda: str(tmp_path / "m.db"))
        database.init_db()
        database.save_active_bet(3, {
            "is_live": True,
            "bets": [{
                "label": "1",
                "match": "Miami Marlins @ Philadelphia Phillies",
                "total_odds": "23.73",
                "is_live": True,
                "legs": [
                    {"match": "Miami Marlins @ Philadelphia Phillies",
                     "player": "Kyle Schwarber", "market": "Hits + Runs + RBIs",
                     "line": "Over 0.5", "group_odds": "1.68"},
                    {"match": "Pittsburgh Pirates @ Arizona Diamondbacks",
                     "player": "Gabriel Moreno", "market": "Hits + Runs + RBIs",
                     "line": "Over 0.5", "group_odds": "1.64"},
                    {"match": "Pittsburgh Pirates @ Arizona Diamondbacks",
                     "player": "Bryan Reynolds", "market": "Hits + Runs + RBIs",
                     "line": "Over 0.5", "group_odds": "1.64"},
                ],
            }],
        })

    def test_separa_un_grupo_por_partido(self, tmp_path, monkeypatch):
        self._guardar(tmp_path, monkeypatch)
        from app.web.service import estado_apuestas

        with patch("app.web.service.buscar_partido", return_value=None), \
             patch("app.web.service.estimate_leg_probability", side_effect=Exception("sin datos")):
            estado = estado_apuestas(3)

        t = estado["tickets"][0]
        assert len(t["grupos"]) == 2          # dos partidos
        assert t["total"] == 3                # tres legs en total
        assert t["odds"] == "23.73"           # la cuota de TODA la apuesta

    def test_cada_grupo_busca_su_propio_partido(self, tmp_path, monkeypatch):
        """Lo que estaba roto: solo se consultaba el partido del encabezado."""
        self._guardar(tmp_path, monkeypatch)
        from app.web.service import estado_apuestas

        with patch("app.web.service.buscar_partido", return_value=None) as mock, \
             patch("app.web.service.estimate_leg_probability", side_effect=Exception("x")):
            estado_apuestas(3)

        consultados = {c.args[0] for c in mock.call_args_list}
        assert len(consultados) == 2

    def test_muestra_la_cuota_del_sub_grupo(self, tmp_path, monkeypatch):
        self._guardar(tmp_path, monkeypatch)
        from app.web.service import estado_apuestas

        with patch("app.web.service.buscar_partido", return_value=None), \
             patch("app.web.service.estimate_leg_probability", side_effect=Exception("x")):
            estado = estado_apuestas(3)

        cuotas = {g["odds"] for g in estado["tickets"][0]["grupos"]}
        assert cuotas == {"1.68", "1.64"}


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


class TestPartidosTerminados:
    """Cuando el partido termina hay que CONGELAR lo que pasó. Antes se
    dejaba de traer el boxscore y la leg volvía a mostrar el promedio
    histórico, perdiendo el resultado real."""

    BOX_FINAL = {
        "George Kirby": {
            "player_id": 1, "is_team_last_pitcher": True, "is_current_pitcher": False,
            "batting_order": None, "batting": {},
            "pitching": {"strikeouts": 3, "outs": 18, "walks": 1, "hits_allowed": 7},
        },
        "Ezequiel Duran": {
            "player_id": 3, "is_team_last_pitcher": False, "batting_order": "400",
            "is_on_bench": False,
            "batting": {"hits": 2, "runs": 1, "rbi": 1, "home_runs": 0,
                        "strikeouts": 1, "walks": 0, "stolen_bases": 0},
            "pitching": {},
        },
    }
    LIVE_FINAL = {
        "inning": 9, "inning_state": "End", "status": "Final",
        "away_team": "Texas Rangers", "home_team": "Seattle Mariners",
        "away_score": 7, "home_score": 2, "current_pitcher": None,
    }
    CAL_FINAL = {
        "game_pk": 1, "status": "Final",
        "away_team": "Texas Rangers", "home_team": "Seattle Mariners",
        "game_time_utc": "2026-07-29T18:10:00Z",
    }

    @pytest.fixture
    def grupo(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/f.db")
        from app.db import database

        monkeypatch.setattr(database, "_db_path", lambda: str(tmp_path / "f.db"))
        database.init_db()
        database.save_active_bet(3, APUESTA)

        from app.web.service import estado_apuestas

        with patch("app.web.service.buscar_partido", return_value=self.CAL_FINAL), \
             patch("app.web.service.get_live_tracking_for_match",
                   return_value=(self.BOX_FINAL, self.LIVE_FINAL)), \
             patch("app.analysis.live_tracking.search_player", side_effect=_buscar_jugador), \
             patch("app.analysis.live_tracking._recent_avg_rate", return_value=1.0):
            return estado_apuestas(3)["tickets"][0]["grupos"][0]

    def test_marca_el_partido_como_terminado(self, grupo):
        assert grupo["terminado"] is True

    def test_conserva_el_marcador_final(self, grupo):
        assert grupo["away_score"] == 7
        assert grupo["home_score"] == 2

    def test_la_leg_que_no_llego_queda_perdida(self, grupo):
        kirby = next(l for l in grupo["legs"] if "Kirby" in l["player"])
        assert kirby["state"] == "lost"
        assert kirby["current"] == 3  # el valor real con el que terminó

    def test_la_leg_cumplida_queda_marcada(self, grupo):
        duran = next(l for l in grupo["legs"] if "Duran" in l["player"])
        assert duran["state"] == "done"

    def test_no_vuelve_al_promedio_historico(self, grupo):
        """El bug: al terminar mostraba '70% en sus últimos 10' en vez del
        resultado real de ese partido."""
        for leg in grupo["legs"]:
            assert "últimos" not in (leg.get("note") or "")


class TestSinFuncionesDuplicadas:
    """Bug real (van dos veces): primero dos `_armar_grupo` en
    app/web/service.py (la vieja, sin el campo `terminado`, pisaba a la
    buena) y después dos `find_dream_combos` en app/analysis/combos.py.
    El test original solo miraba service.py y por eso no agarró la
    segunda — ahora recorre TODO app/."""

    def test_una_sola_definicion_de_cada_funcion_por_archivo(self):
        import re
        from pathlib import Path

        raiz = Path(__file__).resolve().parent.parent / "app"
        archivos = [p for p in raiz.rglob("*.py") if "__pycache__" not in p.parts]
        assert archivos, "no encontré archivos .py en app/"

        problemas = {}
        for archivo in archivos:
            fuente = archivo.read_text(encoding="utf-8")
            nombres = re.findall(r"^def (\w+)", fuente, re.M)
            duplicados = {n for n in nombres if nombres.count(n) > 1}
            if duplicados:
                problemas[str(archivo.relative_to(raiz.parent))] = duplicados

        assert not problemas, f"funciones duplicadas por archivo: {problemas}"
