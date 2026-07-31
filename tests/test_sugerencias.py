"""Sugerencia de línea alternativa: "¿me convenía pedir más?".

Caso real de la captura: Andrew Painter, Golpes Permitidos Over 3.5,
90% en sus últimos 10 y promedio 6.3. Con ese promedio, Over 4.5 o 5.5
mantienen la seguridad y pagan bastante más.
"""
from unittest.mock import patch

from app.analysis.probability import mejor_alternativa, sugerir_lineas

# Últimos 10 de un pitcher que promedia ~6.3 hits permitidos
PARTIDOS = [
    {"date": f"2026-07-{10 + i}", "hits_allowed": v}
    for i, v in enumerate([6, 7, 5, 8, 6, 4, 7, 9, 5, 6])
]


def _sugerir(linea):
    with patch("app.analysis.probability.search_player",
               return_value={"id": 1, "full_name": "Andrew Painter", "position": "Pitcher"}), \
         patch("app.analysis.probability.get_recent_pitching_games", return_value=PARTIDOS):
        return sugerir_lineas("Andrew Painter", "Hits Allowed", linea)


class TestSugerirLineas:
    def test_la_linea_apostada_queda_marcada(self):
        opciones = _sugerir("Over 3.5")
        apostada = [o for o in opciones if o.es_la_apostada]
        assert len(apostada) == 1
        assert apostada[0].linea == 3.5

    def test_calcula_bien_cada_linea(self):
        opciones = {o.linea: o.probabilidad_pct for o in _sugerir("Over 3.5")}
        # Los 10 valores superan 3.5 -> 100%
        assert opciones[3.5] == 100.0
        # 8 de 10 superan 4.5 (los dos 4... en realidad hay un solo 4)
        assert opciones[4.5] == 90.0
        # superan 5.5: 6,7,8,6,7,9,6 = 7 de 10
        assert opciones[5.5] == 70.0


class TestMejorAlternativa:
    def test_sugiere_subir_la_linea_si_sigue_siendo_segura(self):
        """Over 3.5 al 100% cuando 4.5 también da 90%: hay que pedir más."""
        mejor = mejor_alternativa(_sugerir("Over 3.5"), minimo_pct=80.0)
        assert mejor is not None
        assert mejor.linea == 4.5
        assert mejor.probabilidad_pct == 90.0

    def test_no_sugiere_nada_si_la_apostada_ya_era_la_mejor(self):
        """Si estirar la línea ya baja demasiado la probabilidad, no hay
        sugerencia. Recomendar algo peor que lo que la persona eligió
        sería ruido."""
        assert mejor_alternativa(_sugerir("Over 8.5"), minimo_pct=80.0) is None

    def test_para_under_sugiere_bajar_la_linea(self):
        """En Under el que paga más es el número MÁS chico."""
        opciones = _sugerir("Under 9.5")
        mejor = mejor_alternativa(opciones, minimo_pct=80.0)
        assert mejor is not None
        assert mejor.linea < 9.5
