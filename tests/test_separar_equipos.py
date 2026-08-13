"""Bug real: un partido EN CURSO aparecía sin inning, sin marcador y sin
horario -- como si no existiera en el calendario.

La causa era la separación del cruce en dos equipos. Se partía por una
lista fija de separadores (" @ ", " vs ", " - ") y la IA de visión no
siempre escribe el mismo: con "vs." (con punto) el split no encontraba
nada, devolvía UN solo texto gigante como nombre del visitante, y ese
texto no matcheaba contra ningún partido. Sin partido: sin horario, sin
estado en vivo, sin nada.
"""
import pytest

from app.analysis.live_tracking import _split_match
from app.utils.equipos import equipos_en_texto
from app.web.service import _equipos_de


VARIANTES = [
    "Los Angeles Dodgers @ Kansas City Royals",
    "Dodgers @ Royals",
    "Los Angeles Dodgers vs. Kansas City Royals",
    "Los Angeles Dodgers vs Kansas City Royals",
    "Los Angeles Dodgers - Kansas City Royals",
    "Dodgers vs. Royals",
]


class TestEquiposEnTexto:
    @pytest.mark.parametrize("texto", VARIANTES)
    def test_encuentra_los_dos_equipos(self, texto):
        assert equipos_en_texto(texto) == [
            "Los Angeles Dodgers", "Kansas City Royals",
        ]

    def test_respeta_el_orden_de_aparicion(self):
        """El primero es el visitante en "A @ B"."""
        assert equipos_en_texto("Kansas City Royals @ Los Angeles Dodgers") == [
            "Kansas City Royals", "Los Angeles Dodgers",
        ]

    def test_sin_equipos_devuelve_vacio(self):
        assert equipos_en_texto("no hay equipos acá") == []
        assert equipos_en_texto(None) == []


class TestSepararCruce:
    @pytest.mark.parametrize("texto", VARIANTES)
    def test_la_web_separa_bien_todas_las_variantes(self, texto):
        visitante, local = _equipos_de(texto)
        assert "Dodgers" in visitante
        assert "Royals" in local

    @pytest.mark.parametrize("texto", VARIANTES)
    def test_el_tracking_en_vivo_separa_igual(self, texto):
        """Las dos copias tienen que coincidir: si una encuentra el
        partido y la otra no, la leg muestra datos inconsistentes."""
        assert _split_match(texto) == _equipos_de(texto)

    def test_el_separador_con_punto_ya_no_rompe(self):
        """El caso exacto que fallaba: con "vs." el split viejo devolvía
        el texto entero como nombre del visitante."""
        visitante, local = _equipos_de("Los Angeles Dodgers vs. Kansas City Royals")
        assert visitante == "Los Angeles Dodgers"
        assert local == "Kansas City Royals"
        assert "vs" not in visitante.lower()

    def test_texto_desconocido_no_explota(self):
        visitante, local = _equipos_de("Equipo Raro @ Otro Raro")
        assert visitante and isinstance(local, str)
