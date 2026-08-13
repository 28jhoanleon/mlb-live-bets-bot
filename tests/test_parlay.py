"""Cliente de ParlayAPI y su traducción al formato interno.

Se agregó porque The Odds API cobra una consulta POR PARTIDO: un barrido
de 12 partidos gastaba 12 créditos y nos dejó la cuota en negativo. Acá
una sola llamada trae todo el MLB.

Lo delicado es la traducción: ParlayAPI devuelve una fila por (book,
jugador, mercado, línea), y el resto del proyecto espera la forma de
The Odds API. Si esa conversión falla, los picks salen mal sin que nada
avise.
"""
from unittest.mock import patch

import pytest

from app.odds import parlay


FILAS = [
    {"bookmaker": "draftkings", "player": "Aaron Judge",
     "market_key": "player_hits_runs_rbis", "line": 1.5,
     "over_price": -110, "under_price": -110,
     "home_team": "New York Yankees", "away_team": "Kansas City Royals",
     "canonical_event_id": "evt1", "commence_time": "2099-05-01T19:35:00Z"},
    {"bookmaker": "pinnacle", "player": "Aaron Judge",
     "market_key": "player_hits_runs_rbis", "line": 1.5,
     "over_price": -105, "under_price": -115,
     "home_team": "New York Yankees", "away_team": "Kansas City Royals",
     "canonical_event_id": "evt1", "commence_time": "2099-05-01T19:35:00Z"},
    {"bookmaker": "draftkings", "player": "Bobby Witt Jr.",
     "market_key": "player_hits", "line": 0.5,
     "over_price": -160, "under_price": 130,
     "home_team": "New York Yankees", "away_team": "Kansas City Royals",
     "canonical_event_id": "evt1", "commence_time": "2099-05-01T19:35:00Z"},
]


class TestConversionDeCuotas:
    def test_americana_positiva_a_decimal(self):
        assert parlay._a_decimal(290) == 3.9

    def test_americana_negativa_a_decimal(self):
        assert parlay._a_decimal(-110) == 1.909

    def test_una_decimal_se_deja_como_esta(self):
        """No convertir dos veces si ya vino en decimal."""
        assert parlay._a_decimal(1.91) == 1.91

    def test_valor_invalido_devuelve_none(self):
        assert parlay._a_decimal(None) is None
        assert parlay._a_decimal("x") is None


class TestTraduccionAlFormatoInterno:
    def _agrupado(self):
        with patch.object(parlay, "get_all_props", return_value=FILAS):
            return parlay.props_por_evento()

    def test_agrupa_por_partido(self):
        agrupado = self._agrupado()
        assert list(agrupado) == ["evt1"]
        assert agrupado["evt1"]["event"]["home_team"] == "New York Yankees"

    def test_conserva_los_dos_books(self):
        """El consenso entre books es lo que da el devig: perder uno
        arruinaría el cálculo."""
        books = agrupado_books = self._agrupado()["evt1"]["props"]["bookmakers"]
        assert {b["title"] for b in books} == {"draftkings", "pinnacle"}

    def test_cada_lado_queda_como_outcome(self):
        """Over y Under tienen que estar los dos: sin el par no se puede
        devigar."""
        books = self._agrupado()["evt1"]["props"]["bookmakers"]
        dk = next(b for b in books if b["title"] == "draftkings")
        mercado = next(m for m in dk["markets"] if m["key"] == "batter_hits_runs_rbis")
        lados = {o["name"] for o in mercado["outcomes"]}
        assert lados == {"Over", "Under"}

    def test_las_cuotas_quedan_en_decimal(self):
        books = self._agrupado()["evt1"]["props"]["bookmakers"]
        dk = next(b for b in books if b["title"] == "draftkings")
        mercado = next(m for m in dk["markets"] if m["key"] == "batter_hits_runs_rbis")
        for o in mercado["outcomes"]:
            assert o["price"] > 1.0, "quedó en formato americano"

    def test_la_forma_es_la_que_espera_el_resto_del_proyecto(self):
        """group_props_by_outcome consume esta estructura: si cambia, los
        picks salen vacíos sin error visible."""
        from app.analysis.value import group_props_by_outcome

        agrupado = group_props_by_outcome(self._agrupado()["evt1"]["props"])
        assert agrupado, "la traducción no produjo nada consumible"
        clave = "batter_hits_runs_rbis|Aaron Judge|1.5"
        assert clave in agrupado
        assert set(agrupado[clave]) == {"draftkings", "pinnacle"}

    def test_filas_sin_jugador_se_descartan(self):
        filas = [{**FILAS[0], "player": None}]
        with patch.object(parlay, "get_all_props", return_value=filas):
            agrupado = parlay.props_por_evento()
        books = agrupado["evt1"]["props"]["bookmakers"]
        assert all(not m["outcomes"] for b in books for m in b["markets"])


class TestErrores:
    def test_sin_clave_avisa(self, monkeypatch):
        from app.config import settings
        import dataclasses

        monkeypatch.setattr(parlay, "settings",
                            dataclasses.replace(settings, parlay_api_key=""))
        with pytest.raises(parlay.ParlayClientError):
            parlay._get("/sports")

    def test_hay_clave_refleja_la_config(self, monkeypatch):
        from app.config import settings
        import dataclasses

        monkeypatch.setattr(parlay, "settings",
                            dataclasses.replace(settings, parlay_api_key="abc"))
        assert parlay.hay_clave() is True


class TestTraduccionDeMercados:
    """EL bug que hizo que todas las soñadoras salieran mal.

    ParlayAPI nombra todo con el prefijo `player_`, sin distinguir bateo
    de pitcheo. "player_runs" son carreras ANOTADAS (bateo), pero
    aplicado a un pitcher el bot lo interpretaba como carreras
    PERMITIDAS: calculaba "permite >=1 carrera" (~92%) y lo comparaba
    contra el precio de "el pitcher anota" (~29%). Ventaja falsa
    enorme, y el buscador elegía sistemáticamente esos casos: por eso
    todas las legs decían exactamente 91.7% y todos eran pitchers.
    """

    def test_las_carreras_son_de_bateo(self):
        assert parlay.traducir_mercado("player_runs") == "batter_runs_scored"

    def test_las_carreras_permitidas_son_de_pitcheo(self):
        assert parlay.traducir_mercado("player_earned_runs") == "pitcher_earned_runs"

    def test_hits_y_hits_permitidos_no_se_confunden(self):
        assert parlay.traducir_mercado("player_hits") == "batter_hits"
        assert parlay.traducir_mercado("player_hits_allowed") == "pitcher_hits_allowed"

    def test_los_ambiguos_quedan_para_resolver_por_rol(self):
        """Los ponches de un pitcher son los que reparte; los de un
        bateador, los que se come. Ahí el rol SÍ es la señal correcta."""
        assert parlay.traducir_mercado("player_strikeouts") == "player_strikeouts"

    def test_un_mercado_desconocido_se_descarta(self):
        """Mejor perder un prop que interpretarlo mal."""
        assert parlay.traducir_mercado("player_first_hit") is None
        assert parlay.traducir_mercado("cualquier_cosa") is None


class TestElMercadoMandaSobreElRol:
    def test_un_mercado_de_bateo_sobre_un_pitcher_se_rechaza(self):
        """Con el DH universal los pitchers no batean: esto no es una
        oportunidad, es un error de lectura."""
        from unittest.mock import patch

        from app.analysis import probability as prob
        from app.analysis.probability import ProbabilityError

        prob.limpiar_cache_estimaciones()
        with patch.object(prob, "search_player",
                          return_value={"id": 1, "full_name": "Jacob deGrom",
                                        "position": "Pitcher"}):
            with pytest.raises(ProbabilityError):
                prob.estimate_leg_probability("Jacob deGrom", "batter_runs_scored", "Over 0.5")

    def test_un_mercado_de_pitcheo_usa_stats_de_pitcheo(self):
        from unittest.mock import patch

        from app.analysis import probability as prob

        juegos = [{"date": f"2026-08-{i+1:02d}", "earned_runs": 2} for i in range(10)]
        prob.limpiar_cache_estimaciones()
        with patch.object(prob, "search_player",
                          return_value={"id": 1, "full_name": "Jacob deGrom",
                                        "position": "Pitcher"}), \
             patch.object(prob, "get_recent_pitching_games", return_value=juegos) as pitcheo, \
             patch.object(prob, "get_recent_hitting_games") as bateo:
            prob.estimate_leg_probability("Jacob deGrom", "pitcher_earned_runs", "Over 0.5")

        assert pitcheo.called and not bateo.called
