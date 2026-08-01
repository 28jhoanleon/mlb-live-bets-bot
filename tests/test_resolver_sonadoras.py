"""Bug real y grave: el bot marcaba soñadoras como "se dio 🎉" cuando en
Stake figuraban PERDIDAS.

Tres causas que se sumaban en _resolver_leg:

1. Agarraba `partidos[0]`, el partido MÁS RECIENTE del jugador, sin
   mirar la fecha en que se había sugerido el combo.
2. Usaba el gameLog de BATEO incluso para pitchers: un "Strikeouts Over
   7.5" de un lanzador miraba sus ponches como bateador (casi siempre
   0), así que cualquier Under daba ganado.
3. Si el jugador no jugó ese día, igual evaluaba contra otro partido.
"""
from unittest.mock import patch

from app.bot.handlers import combos_historial as ch


def _leg(player="Jake Burger", market="Hits", line="Over 0.5"):
    return {"player": player, "market": market, "line": line}


class TestResuelveContraLaFechaCorrecta:
    def test_no_usa_el_partido_mas_reciente_sino_el_del_dia(self):
        """El jugador NO pegó hit el día sugerido (30/07) pero sí al día
        siguiente. Antes se evaluaba contra el más reciente y la daba
        por ganada."""
        partidos = [
            {"date": "2026-07-31", "hits": 2, "runs": 1, "rbi": 0},  # más reciente
            {"date": "2026-07-30", "hits": 0, "runs": 0, "rbi": 0},  # el que importa
        ]
        with patch.object(ch, "search_player",
                          return_value={"id": 1, "full_name": "Jake Burger", "position": "Infielder"}), \
             patch.object(ch, "get_recent_hitting_games", return_value=partidos):
            resultado = ch._resolver_leg(_leg(), "2026-07-30T12:58:00+00:00")

        assert resultado is False, (
            "marcó como cumplida una leg usando el partido del día "
            "siguiente en vez del día en que se sugirió"
        )

    def test_acierta_cuando_de_verdad_se_dio(self):
        partidos = [
            {"date": "2026-07-31", "hits": 0, "runs": 0, "rbi": 0},
            {"date": "2026-07-30", "hits": 2, "runs": 1, "rbi": 0},
        ]
        with patch.object(ch, "search_player",
                          return_value={"id": 1, "full_name": "Jake Burger", "position": "Infielder"}), \
             patch.object(ch, "get_recent_hitting_games", return_value=partidos):
            assert ch._resolver_leg(_leg(), "2026-07-30T12:58:00+00:00") is True

    def test_si_no_jugo_ese_dia_no_inventa_resultado(self):
        partidos = [{"date": "2026-07-28", "hits": 3, "runs": 1, "rbi": 2}]
        with patch.object(ch, "search_player",
                          return_value={"id": 1, "full_name": "Jake Burger", "position": "Infielder"}), \
             patch.object(ch, "get_recent_hitting_games", return_value=partidos):
            assert ch._resolver_leg(_leg(), "2026-07-30T12:58:00+00:00") is None


class TestUsaElGameLogSegunElRol:
    def test_pitcher_usa_stats_de_pitcheo(self):
        """Un Strikeouts de pitcher tiene que mirar los ponches que
        REPARTIÓ, no los que se comió bateando."""
        pitcheo = [{"date": "2026-07-30", "strikeouts": 9, "outs": 18}]
        with patch.object(ch, "search_player",
                          return_value={"id": 2, "full_name": "Dylan Cease", "position": "Pitcher"}), \
             patch.object(ch, "get_recent_pitching_games", return_value=pitcheo) as pitch_mock, \
             patch.object(ch, "get_recent_hitting_games") as hit_mock:
            resultado = ch._resolver_leg(
                _leg("Dylan Cease", "Strikeouts", "Over 7.5"), "2026-07-30T12:58:00+00:00"
            )

        assert pitch_mock.called, "no usó el gameLog de pitcheo para un pitcher"
        assert not hit_mock.called, "usó stats de BATEO para un pitcher"
        assert resultado is True

    def test_pitcher_que_no_llego_a_la_linea_da_perdida(self):
        pitcheo = [{"date": "2026-07-30", "strikeouts": 4, "outs": 15}]
        with patch.object(ch, "search_player",
                          return_value={"id": 2, "full_name": "Dylan Cease", "position": "Pitcher"}), \
             patch.object(ch, "get_recent_pitching_games", return_value=pitcheo):
            resultado = ch._resolver_leg(
                _leg("Dylan Cease", "Strikeouts", "Over 7.5"), "2026-07-30T12:58:00+00:00"
            )
        assert resultado is False


class TestResolverCombo:
    def test_una_leg_perdida_pierde_todo_el_combo(self):
        """El caso de la captura: 3 de 4 legs fallaron y el combo
        figuraba como ganado."""
        combo = {
            "creado_en": "2026-07-30T12:58:00+00:00",
            "legs": [_leg("A"), _leg("B"), _leg("C")],
        }
        # Solo el segundo pegó hit
        def _por_jugador(nombre):
            return {"id": 1, "full_name": nombre, "position": "Infielder"}

        partidos_ok = [{"date": "2026-07-30", "hits": 1, "runs": 0, "rbi": 0}]
        partidos_mal = [{"date": "2026-07-30", "hits": 0, "runs": 0, "rbi": 0}]
        llamadas = {"n": 0}

        def _games(pid, last_n=15):
            llamadas["n"] += 1
            return partidos_ok if llamadas["n"] == 2 else partidos_mal

        with patch.object(ch, "search_player", side_effect=_por_jugador), \
             patch.object(ch, "get_recent_hitting_games", side_effect=_games):
            assert ch._resolver_combo(combo) == "perdida"

    def test_sin_fecha_no_resuelve(self):
        assert ch._resolver_combo({"legs": [_leg()]}) is None

    def test_combo_sin_legs_no_da_ganado(self):
        """all([]) es True en Python: un combo vacío daría 'ganada'."""
        assert ch._resolver_combo({"creado_en": "2026-07-30", "legs": []}) is None
