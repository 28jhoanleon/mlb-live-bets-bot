"""Turnos al bate restantes.

"Necesita 1 hit" no dice nada solo: con 3 turnos por delante la leg está
viva, con medio turno en la novena está liquidada. Esta estimación es
la que convierte el número en información útil.
"""
from app.analysis.turnos import _orden_a_numero, describir_turnos, turnos_restantes


class TestOrdenAlBate:
    def test_lee_el_puesto_del_titular(self):
        """La MLB API codifica el orden como "301" = tercer bate."""
        assert _orden_a_numero("301") == 3
        assert _orden_a_numero("100") == 1
        assert _orden_a_numero("900") == 9

    def test_lee_el_puesto_de_un_suplente(self):
        """"1101" es quien entró por el primer bate."""
        assert _orden_a_numero("1101") is None or _orden_a_numero("1101") <= 9

    def test_sin_orden_devuelve_none(self):
        assert _orden_a_numero(None) is None
        assert _orden_a_numero("") is None


class TestTurnosRestantes:
    def test_temprano_en_el_partido_quedan_varios(self):
        turnos = turnos_restantes("300", inning=2, inning_state="Top",
                                  es_equipo_visitante=True, outs=1)
        assert turnos is not None and turnos >= 2

    def test_al_final_del_partido_quedan_pocos(self):
        turnos = turnos_restantes("300", inning=9, inning_state="Bottom",
                                  es_equipo_visitante=True, outs=2)
        assert turnos is not None and turnos <= 1

    def test_mas_avanzado_el_partido_menos_turnos(self):
        """Lo esencial: el número tiene que bajar a medida que avanza."""
        temprano = turnos_restantes("300", 2, "Top", True, 0)
        mitad = turnos_restantes("300", 5, "Top", True, 0)
        tarde = turnos_restantes("300", 8, "Top", True, 0)
        assert temprano > mitad >= tarde

    def test_el_visitante_y_el_local_no_batean_a_la_vez(self):
        """En la parte alta batea el visitante; el local espera su mitad."""
        visitante = turnos_restantes("300", 5, "Top", es_equipo_visitante=True, outs=2)
        local = turnos_restantes("300", 5, "Top", es_equipo_visitante=False, outs=2)
        assert local >= visitante

    def test_sin_datos_no_inventa(self):
        assert turnos_restantes(None, 5, "Top", True, 1) is None
        assert turnos_restantes("300", None, "Top", True, 1) is None

    def test_nunca_devuelve_negativo(self):
        assert turnos_restantes("900", 9, "Bottom", True, 2) >= 0


class TestDescripcion:
    def test_texto_segun_cantidad(self):
        assert describir_turnos(0) == "sin turnos por delante"
        assert "1 turno" in describir_turnos(1)
        assert "3 turnos" in describir_turnos(3)

    def test_sin_dato_no_muestra_nada(self):
        assert describir_turnos(None) == ""


class TestEnLaWeb:
    def test_una_leg_ya_cumplida_no_muestra_turnos(self):
        """Si ya está asegurada, cuántos turnos queden es irrelevante."""
        from app.web.service import _turnos_de

        class _Status:
            player = "X"
            already_hit = True
            perdida = False

        assert _turnos_de({}, _Status(), {"X": {"batting_order": "300"}},
                          {"inning": 3, "inning_state": "Top", "outs": 1}) == ""

    def test_un_pitcher_no_muestra_turnos_al_bate(self):
        from app.web.service import _turnos_de

        class _Status:
            player = "P"
            already_hit = False
            perdida = False

        boxscore = {"P": {"batting_order": "000", "is_current_pitcher": True}}
        assert _turnos_de({}, _Status(), boxscore,
                          {"inning": 3, "inning_state": "Top", "outs": 1}) == ""

    def test_un_bateador_en_curso_si_los_muestra(self):
        from app.web.service import _turnos_de

        class _Status:
            player = "B"
            already_hit = False
            perdida = False

        boxscore = {"B": {"batting_order": "200", "team_side": "away"}}
        texto = _turnos_de({}, _Status(), boxscore,
                           {"inning": 3, "inning_state": "Top", "outs": 1})
        assert "turno" in texto
