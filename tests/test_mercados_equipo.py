"""Mercados de EQUIPO ("Royals, bases por bolas Over 2.5").

Antes se mostraban como "Sin jugador — Sin datos suficientes", que
parecía un error del bot. La MLB API expone gameLog por equipo, así que
es la misma lógica de siempre un nivel más arriba.

Los de PARTIDO ("Partido, ponches Under 14.5") siguen sin estimarse a
propósito: son los dos equipos juntos y dependen de quiénes lancen ese
día, cosa que el historial del partido no captura.
"""
from unittest.mock import patch

import pytest

from app.analysis.probability import ProbabilityError, estimate_team_probability
from app.mlb import team_stats
from app.mlb.team_stats import campos_de_mercado_equipo, es_mercado_de_pitcheo


class TestMapeoDeMercados:
    def test_reconoce_los_mercados_de_stake(self):
        assert campos_de_mercado_equipo("bases por bolas del bateador") == ["walks"]
        assert campos_de_mercado_equipo("Hits") == ["hits"]
        assert campos_de_mercado_equipo("Carreras") == ["runs"]
        assert campos_de_mercado_equipo("Bases Totales") == ["total_bases"]

    def test_prefiere_el_mas_especifico(self):
        """"bases por bolas" no puede caer en "bases totales"."""
        assert campos_de_mercado_equipo("bases por bolas") == ["walks"]

    def test_un_mercado_desconocido_devuelve_none(self):
        """Mejor no reconocerlo que mapearlo mal y dar un número falso."""
        assert campos_de_mercado_equipo("algo que no existe") is None

    def test_distingue_pitcheo_de_ofensiva(self):
        """Los ponches que un equipo REPARTE salen de su pitcheo; los
        que se COME, de su ofensiva."""
        assert es_mercado_de_pitcheo("ponches permitidos")
        assert not es_mercado_de_pitcheo("bases por bolas del bateador")


def _juegos(valores, campo="walks"):
    return [{"date": f"2026-08-{i+1:02d}", campo: v} for i, v in enumerate(valores)]


class TestEstimarEquipo:
    def test_estima_con_el_gamelog_del_equipo(self):
        # 8 de 10 partidos con más de 2.5 caminatas
        valores = [4, 3, 5, 1, 4, 3, 6, 2, 4, 3]
        with patch.object(team_stats, "get", return_value={"stats": [{"splits": [
            {"date": f"2026-08-{i+1:02d}", "stat": {"baseOnBalls": v}}
            for i, v in enumerate(valores)
        ]}]}):
            est = estimate_team_probability("Kansas City Royals",
                                            "bases por bolas del bateador", "Over 2.5")
        assert est.team == "Kansas City Royals"
        assert est.sample_size == 10
        # Con suavizado: (8+1)/(10+2) = 75%, no 80%
        assert est.probability_pct == 75.0

    def test_aplica_el_mismo_suavizado_que_los_jugadores(self):
        """10 de 10 no puede dar 100%: la muestra es chica."""
        with patch.object(team_stats, "get", return_value={"stats": [{"splits": [
            {"date": f"2026-08-{i+1:02d}", "stat": {"baseOnBalls": 9}}
            for i in range(10)
        ]}]}):
            est = estimate_team_probability("Kansas City Royals",
                                            "bases por bolas", "Over 2.5")
        assert est.probability_pct < 100.0

    def test_equipo_desconocido_avisa(self):
        with pytest.raises(ProbabilityError, match="equipo"):
            estimate_team_probability("Equipo Inventado", "hits", "Over 5.5")

    def test_mercado_no_reconocido_avisa(self):
        with pytest.raises(ProbabilityError, match="no reconocido"):
            estimate_team_probability("Kansas City Royals", "vaya a saber qué", "Over 2.5")

    def test_sin_partidos_avisa_en_vez_de_inventar(self):
        with patch.object(team_stats, "get", return_value={"stats": []}):
            with pytest.raises(ProbabilityError):
                estimate_team_probability("Kansas City Royals", "hits", "Over 5.5")


class TestEnLaWeb:
    def test_el_mercado_de_equipo_ahora_se_estima(self):
        from app.web.service import _leg_de_equipo

        leg = {"ambito": "equipo", "team": "Kansas City Royals",
               "market": "bases por bolas del bateador", "line": "Over 2.5"}
        with patch.object(team_stats, "get", return_value={"stats": [{"splits": [
            {"date": f"2026-08-{i+1:02d}", "stat": {"baseOnBalls": 4}} for i in range(10)
        ]}]}):
            resultado = _leg_de_equipo(leg)

        assert resultado["state"] != "unknown", "sigue sin estimar el mercado de equipo"
        assert "en sus últimos" in resultado["note"]


class TestApuestasViejasSinEquipo:
    """Las apuestas guardadas ANTES de que la visión extrajera "team" no
    traen el equipo. Antes caían al mensaje de "mercado de partido", que
    hacía parecer que la función de equipos no andaba cuando en realidad
    faltaba el dato de entrada."""

    def test_avisa_que_hay_que_reenviar_la_captura(self):
        from app.web.service import _leg_de_equipo

        vieja = {"player": None, "market": "Bases por bolas del bateador",
                 "line": "Over 2.5", "match": "Colorado Rockies @ Kansas City Royals"}
        nota = _leg_de_equipo(vieja)["note"]

        assert "reenviá" in nota, f"no explica qué hacer: {nota}"
        assert "pitchers del día" not in nota, (
            "lo confunde con un mercado de partido: son cosas distintas"
        )

    def test_no_adivina_cual_de_los_dos_equipos_es(self):
        """Mostrar el equipo equivocado sería peor que no mostrar nada."""
        from app.web.service import _leg_de_equipo

        vieja = {"player": None, "market": "Bases por bolas del bateador",
                 "line": "Over 2.5", "match": "Colorado Rockies @ Kansas City Royals"}
        salida = _leg_de_equipo(vieja)
        assert salida["state"] == "unknown"
        # No inventa cuál de los dos equipos del partido es
        assert "Rockies" not in salida["note"] and "Royals" not in salida["note"]


class TestDetalleDeEquipo:
    """Bug real: en la línea principal el mercado de equipo se estimaba
    bien, pero al abrir el botón "+" respondía "No encontré a 'Texas
    Rangers' en el roster actual de MLB". El detalle llamaba siempre a la
    versión de jugador, que busca un JUGADOR con ese nombre."""

    def _payload(self):
        """Respuesta cruda de la MLB API, como la recibe team_stats."""
        valores = [4, 3, 5, 1, 4, 3, 6, 2, 4, 3]
        return {"stats": [{"splits": [
            {"date": f"2026-08-{i+1:02d}", "stat": {"baseOnBalls": v}}
            for i, v in enumerate(valores)
        ]}]}

    def test_el_boton_mas_trae_el_detalle_del_equipo(self):
        from app.web.service import detalle_leg

        with patch.object(team_stats, "get", return_value=self._payload()):
            salida = detalle_leg(
                "Texas Rangers", "Equipo, bases por bolas del bateador", "Over 3.5"
            )

        assert salida["player"] == "Texas Rangers"
        assert len(salida["games"]) == 10
        assert salida["games"][0]["date"] == "2026-08-01"

    def test_las_alternativas_de_linea_tambien_andan_para_equipos(self):
        from app.analysis.probability import sugerir_lineas

        with patch.object(team_stats, "get", return_value=self._payload()):
            opciones = sugerir_lineas(
                "Texas Rangers", "Equipo, bases por bolas del bateador", "Over 3.5"
            )

        assert opciones, "no calculó líneas alternativas para el equipo"
        assert any(o.es_la_apostada for o in opciones)

    def test_un_jugador_sigue_yendo_por_el_camino_de_jugador(self):
        """No romper lo que ya andaba: un nombre que no es equipo tiene
        que seguir buscándose en el roster."""
        from app.web.service import detalle_leg

        with patch("app.utils.equipos.id_equipo", return_value=None), \
             patch("app.analysis.probability.search_player",
                   return_value={"id": 1, "full_name": "Aaron Judge", "position": "Hitter"}), \
             patch("app.analysis.probability.get_recent_hitting_games",
                   return_value=[{"date": "2026-08-01", "hits": 2} for _ in range(10)]):
            salida = detalle_leg("Aaron Judge", "batter_hits", "Over 0.5")

        assert salida["player"] == "Aaron Judge"
