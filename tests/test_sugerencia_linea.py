"""Sugerir una línea mejor del mismo mercado.

Caso real: se apostó "Andrew Painter — Hits Allowed Over 3.5" y el
pitcher promedia 6.3. Entró el 90% de las veces, pero pagaba poco
justamente porque era fácil. Si "Over 5.5" también entraba seguido,
ésa era la apuesta: misma confianza, mejor cuota.
"""
from app.analysis.probability import _PISO_SUGERENCIA, _sugerir_linea


class TestSugerirLinea:
    def test_sugiere_una_linea_mas_exigente_cuando_sobra_margen(self):
        # Diez partidos, todos muy por encima de 3.5
        valores = [6, 7, 5, 8, 6, 6, 7, 4, 9, 6]
        sug = _sugerir_linea(valores, "Over", 3.5, 90.0)
        assert sug is not None
        assert "Over" in sug
        # Tiene que sugerir algo MÁS exigente que 3.5
        numero = float(sug.split()[1])
        assert numero > 3.5

    def test_no_sugiere_nada_si_la_linea_ya_estaba_justa(self):
        """Si apenas llega, empujar a una línea más alta sería malo."""
        valores = [4, 3, 5, 2, 4, 3, 6, 1, 4, 3]
        assert _sugerir_linea(valores, "Over", 3.5, 50.0) is None

    def test_no_sugiere_si_la_apuesta_original_es_floja(self):
        """Con probabilidad baja, sugerir algo más exigente es empeorar."""
        valores = [1, 0, 2, 1, 0, 1, 3, 0, 1, 2]
        assert _sugerir_linea(valores, "Over", 3.5, 10.0) is None

    def test_la_sugerencia_siempre_supera_el_piso(self):
        valores = [6, 7, 5, 8, 6, 6, 7, 4, 9, 6]
        sug = _sugerir_linea(valores, "Over", 3.5, 90.0)
        pct = float(sug.split("en ")[1].replace("%", ""))
        assert pct >= _PISO_SUGERENCIA

    def test_funciona_para_under(self):
        """En Under, 'más exigente' es una línea más BAJA."""
        valores = [1, 0, 2, 1, 0, 1, 0, 0, 1, 2]
        sug = _sugerir_linea(valores, "Under", 5.5, 100.0)
        assert sug is not None
        numero = float(sug.split()[1])
        assert numero < 5.5

    def test_sin_valores_no_explota(self):
        assert _sugerir_linea([], "Over", 3.5, 90.0) is None
