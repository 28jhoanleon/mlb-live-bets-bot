"""Statcast: parseo del CSV de Baseball Savant.

Los tests no tocan la red: mockean la descarga. Lo que se verifica es
el parseo y el cruce por nombre, que es donde se puede romper si Savant
cambia el formato del CSV.
"""
from unittest.mock import patch

import pytest

from app.mlb import statcast

CSV_FALSO = (
    '"last_name, first_name",player_id,year,pa,bip,ba,est_ba,slg,est_slg,woba,est_woba\n'
    '"Judge, Aaron",592450,2026,600,400,0.310,0.335,0.690,0.710,0.440,0.460\n'
    '"Meidroth, Chase",700001,2026,400,300,0.275,0.255,0.360,0.340,0.310,0.300\n'
)


@pytest.fixture(autouse=True)
def limpiar_cache():
    statcast._cache.clear()
    statcast._cache_fecha = None
    yield
    statcast._cache.clear()
    statcast._cache_fecha = None


class TestParseoDelCsv:
    def test_convierte_apellido_nombre_a_nombre_apellido(self):
        with patch.object(statcast, "_descargar", return_value=CSV_FALSO):
            tabla = statcast.get_expected_stats("batter", 2026)
        assert "aaron judge" in tabla
        assert tabla["aaron judge"]["nombre"] == "Aaron Judge"
        assert tabla["aaron judge"]["xba"] == 0.335

    def test_csv_vacio_avisa_en_vez_de_devolver_nada(self):
        """Si Savant cambia el formato preferimos enterarnos, no seguir
        calladamente con una tabla vacía."""
        with patch.object(statcast, "_descargar", return_value="col_a,col_b\n1,2\n"):
            with pytest.raises(statcast.StatcastError):
                statcast.get_expected_stats("batter", 2026)

    def test_cachea_para_no_bajar_el_csv_en_cada_consulta(self):
        with patch.object(statcast, "_descargar", return_value=CSV_FALSO) as bajar:
            statcast.get_expected_stats("batter", 2026)
            statcast.get_expected_stats("batter", 2026)
            statcast.get_expected_stats("batter", 2026)
        assert bajar.call_count == 1


class TestBuscarJugador:
    def test_encuentra_por_nombre_exacto(self):
        with patch.object(statcast, "_descargar", return_value=CSV_FALSO):
            datos = statcast.buscar_jugador("Aaron Judge")
        assert datos["nombre"] == "Aaron Judge"

    def test_tolera_error_de_tipeo(self):
        """Mismo criterio que en el resto del proyecto: la IA de visión
        cambia una letra y no queremos perder al jugador por eso."""
        with patch.object(statcast, "_descargar", return_value=CSV_FALSO):
            datos = statcast.buscar_jugador("Chase Meldroth")  # con L
        assert datos is not None
        assert datos["nombre"] == "Chase Meidroth"

    def test_jugador_inexistente_devuelve_none(self):
        with patch.object(statcast, "_descargar", return_value=CSV_FALSO):
            assert statcast.buscar_jugador("Fulano Detal") is None

    def test_si_savant_no_responde_devuelve_none_sin_romper(self):
        """Savant caído no puede tumbar un comando del bot."""
        with patch.object(statcast, "_descargar", side_effect=statcast.StatcastError("caido")):
            assert statcast.buscar_jugador("Aaron Judge") is None


class TestDiferenciaXba:
    def test_positivo_cuando_batea_mejor_de_lo_que_muestra(self):
        with patch.object(statcast, "_descargar", return_value=CSV_FALSO):
            judge = statcast.buscar_jugador("Aaron Judge")
        assert statcast.diferencia_xba(judge) == 0.025

    def test_negativo_cuando_viene_con_suerte(self):
        with patch.object(statcast, "_descargar", return_value=CSV_FALSO):
            chase = statcast.buscar_jugador("Chase Meidroth")
        assert statcast.diferencia_xba(chase) == -0.020

    def test_sin_datos_devuelve_none(self):
        assert statcast.diferencia_xba({}) is None
