"""Una captura = una apuesta.

Dos bugs distintos que aparecieron con cupones reales de Stake:

1. Un cupón con cuatro bloques ("Multi apuesta del mismo partido", uno
   por partido, cada uno con su cuota parcial) se leía como cuatro
   apuestas separadas. Veías cinco tarjetas de "2 TRAMOS" cuando habías
   jugado una sola combinada.

2. Otros cupones listan solo el ESCUDO del equipo, sin el nombre del
   cruce. La IA no puede leer un logo, así que la leg llegaba sin
   partido y en la web salía "? @ ?" sin datos en vivo.
"""
from unittest.mock import patch

from app.analysis.tickets import unificar_cupon


class TestUnificarCupon:
    def _bloques(self):
        """El caso real: 4 bloques, uno trae la cuota del cupón entero."""
        return [
            {"total_odds": "15.67", "legs": [{"player": "A"}, {"player": "B"}]},
            {"legs": [{"player": "C"}, {"player": "D"}]},
            {"legs": [{"player": "E"}, {"player": "F"}]},
            {"legs": [{"player": "G"}, {"player": "H"}, {"player": "I"}]},
        ]

    def test_los_bloques_se_unen_en_una_apuesta(self):
        assert len(unificar_cupon(self._bloques())) == 1

    def test_conserva_todos_los_tramos(self):
        assert len(unificar_cupon(self._bloques())[0]["legs"]) == 9

    def test_conserva_la_cuota_del_cupon(self):
        assert unificar_cupon(self._bloques())[0]["total_odds"] == "15.67"

    def test_dos_apuestas_con_cuota_propia_no_se_tocan(self):
        """La señal de que son distintas es que cada una tenga SU cuota
        total. Unirlas ahí sería el error opuesto."""
        separadas = [
            {"total_odds": "2.0", "legs": [{"player": "A"}]},
            {"total_odds": "3.0", "legs": [{"player": "B"}]},
        ]
        assert len(unificar_cupon(separadas)) == 2

    def test_una_sola_no_se_toca(self):
        una = [{"total_odds": "2.0", "legs": [{"player": "A"}]}]
        assert unificar_cupon(una) == una

    def test_conserva_la_marca_de_borrador(self):
        bloques = [
            {"legs": [{"player": "A"}], "borrador": True},
            {"legs": [{"player": "B"}]},
        ]
        assert unificar_cupon(bloques)[0].get("borrador") is True


class TestDeducirPartido:
    """Cuando el cupón solo muestra escudos, el partido se deduce del
    equipo del jugador."""

    def test_encuentra_el_partido_por_el_jugador(self):
        from app.web import service

        calendario = [
            {"away_team": "Boston Red Sox", "home_team": "Miami Marlins"},
            {"away_team": "Chicago Cubs", "home_team": "St. Louis Cardinals"},
        ]
        with patch("app.mlb.players.search_player",
                   return_value={"id": 1, "full_name": "Ceddanne Rafaela",
                                 "team": "Boston Red Sox"}), \
             patch("app.mlb.schedule.get_schedule_cacheado", return_value=calendario):
            assert service._partido_del_jugador("Ceddanne Rafaela") == \
                "Boston Red Sox @ Miami Marlins"

    def test_si_no_encuentra_al_jugador_devuelve_none(self):
        from app.web import service

        with patch("app.mlb.players.search_player", return_value=None):
            assert service._partido_del_jugador("Fulano") is None

    def test_si_el_equipo_no_juega_hoy_devuelve_none(self):
        """Mejor "? @ ?" que asignarle un partido equivocado."""
        from app.web import service

        with patch("app.mlb.players.search_player",
                   return_value={"id": 1, "full_name": "X", "team": "Seattle Mariners"}), \
             patch("app.mlb.schedule.get_schedule_cacheado",
                   return_value=[{"away_team": "Cubs", "home_team": "Cardinals"}]):
            assert service._partido_del_jugador("X") is None

    def test_si_falla_la_api_no_rompe(self):
        from app.web import service

        with patch("app.mlb.players.search_player", side_effect=ConnectionError("cortó")):
            assert service._partido_del_jugador("X") is None


class TestPartidoInservible:
    """No alcanza con que el partido venga VACÍO: la IA a veces devuelve
    un texto que no identifica a nadie ("? @ ?", un guión, el nombre del
    mercado). En la web eso salía como "? @ ?" y sin datos en vivo,
    porque la deducción solo se activaba con el texto vacío."""

    def test_un_texto_sin_equipos_dispara_la_deduccion(self):
        from app.utils.equipos import equipos_en_texto

        for basura in ("", "? @ ?", "-", "Home Runs"):
            assert len(equipos_en_texto(basura)) < 2, basura

    def test_un_partido_de_verdad_no_la_dispara(self):
        from app.utils.equipos import equipos_en_texto

        assert len(equipos_en_texto("Boston Red Sox @ Miami Marlins")) == 2

    def test_el_codigo_usa_ese_criterio(self):
        import pathlib

        fuente = pathlib.Path("app/web/service.py").read_text()
        assert "len(equipos_en_texto(nombre)) < 2" in fuente


class TestPartidoEnDiasCercanos:
    def test_busca_tambien_manana(self):
        """Una apuesta puede ser para el partido de mañana."""
        from unittest.mock import patch
        from datetime import date

        from app.web import service

        manana = date(2026, 8, 15)

        def _por_dia(dia=None):
            if dia == manana:
                return [{"away_team": "Boston Red Sox", "home_team": "Miami Marlins"}]
            return []

        with patch("app.mlb.players.search_player",
                   return_value={"id": 1, "full_name": "X", "team": "Boston Red Sox"}), \
             patch("app.mlb.schedule.get_schedule_cacheado", side_effect=_por_dia), \
             patch("app.utils.tiempo.hoy_local", return_value=date(2026, 8, 14)):
            assert service._partido_del_jugador("X") == "Boston Red Sox @ Miami Marlins"


class TestCabeceraDeCuota:
    """Solo aparecía The Odds API: ParlayAPI nombra distinto la cabecera
    de créditos y buscábamos un único nombre."""

    def test_se_prueban_varios_nombres(self):
        import pathlib

        fuente = pathlib.Path("app/odds/parlay.py").read_text()
        for cabecera in ("x-requests-remaining", "x-credits-remaining"):
            assert cabecera in fuente
