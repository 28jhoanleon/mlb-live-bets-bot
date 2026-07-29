"""Tests de la fusión de capturas múltiples.

Caso de uso: una combinada de 8 legs no entra en una sola captura, así
que el usuario manda 2 o 3 fotos como álbum. Antes cada foto pisaba a la
anterior y /refresh solo actualizaba la última.
"""
from app.bot.media_group import (
    agregar_imagen,
    merge_analyses,
    recuperar_y_limpiar,
)


class TestMergeAnalyses:
    def test_junta_legs_de_varias_capturas(self):
        a = {"is_parlay": True, "is_live": False, "legs": [{"player": "A", "market": "Hits", "line": "Over 0.5"}]}
        b = {"is_parlay": True, "is_live": False, "legs": [{"player": "B", "market": "Walks", "line": "Over 1.5"}]}
        merged = merge_analyses([a, b])
        assert len(merged["legs"]) == 2

    def test_deduplica_legs_repetidas(self):
        """Al scrollear una combinada larga es normal que dos capturas
        se superpongan. Sin deduplicar, el conteo de 'X de Y cumplidas'
        quedaría mal."""
        leg = {"player": "Duran", "market": "Hits", "line": "Over 0.5"}
        a = {"legs": [leg, {"player": "Kirby", "market": "Strikeouts", "line": "Over 3.5"}]}
        b = {"legs": [leg, {"player": "Judge", "market": "Home Runs", "line": "Over 0.5"}]}
        merged = merge_analyses([a, b])
        assert len(merged["legs"]) == 3
        nombres = [l["player"] for l in merged["legs"]]
        assert nombres.count("Duran") == 1

    def test_deduplica_ignorando_mayusculas_y_espacios(self):
        a = {"legs": [{"player": "Aaron Judge", "market": "Hits", "line": "Over 0.5"}]}
        b = {"legs": [{"player": " aaron judge ", "market": "HITS", "line": "over 0.5"}]}
        assert len(merge_analyses([a, b])["legs"]) == 1

    def test_alcanza_que_una_captura_sea_en_vivo(self):
        """Si el usuario capturó el encabezado 'En vivo' solo en una de
        las fotos, la apuesta sigue siendo en vivo."""
        a = {"is_live": False, "legs": [{"player": "A", "market": "Hits", "line": "Over 0.5"}]}
        b = {"is_live": True, "legs": [{"player": "B", "market": "Hits", "line": "Over 0.5"}]}
        assert merge_analyses([a, b])["is_live"] is True

    def test_una_sola_leg_no_es_combinada(self):
        a = {"legs": [{"player": "A", "market": "Hits", "line": "Over 0.5"}]}
        assert merge_analyses([a])["is_parlay"] is False

    def test_varias_legs_son_combinada(self):
        a = {"legs": [{"player": "A", "market": "Hits", "line": "Over 0.5"}]}
        b = {"legs": [{"player": "B", "market": "Walks", "line": "Over 1.5"}]}
        assert merge_analyses([a, b])["is_parlay"] is True

    def test_sin_legs_no_rompe(self):
        assert merge_analyses([{"legs": []}, {"legs": []}])["legs"] == []


class TestBufferDeAlbum:
    def test_acumula_y_devuelve_en_orden(self):
        agregar_imagen("G1", b"foto1")
        agregar_imagen("G1", b"foto2")
        assert recuperar_y_limpiar("G1") == [b"foto1", b"foto2"]

    def test_limpia_despues_de_recuperar(self):
        """El buffer es efímero: si no se limpia, un álbum viejo
        contaminaría el siguiente."""
        agregar_imagen("G2", b"foto")
        recuperar_y_limpiar("G2")
        assert recuperar_y_limpiar("G2") == []

    def test_albumes_distintos_no_se_mezclan(self):
        agregar_imagen("A", b"deA")
        agregar_imagen("B", b"deB")
        assert recuperar_y_limpiar("A") == [b"deA"]
        assert recuperar_y_limpiar("B") == [b"deB"]


class TestSumarACombinadaGuardada:
    """El '+' en el pie de foto suma la captura nueva a la apuesta ya
    guardada, en vez de reemplazarla. Sirve para combinadas largas
    mandadas de a una foto por vez."""

    def _leg(self, player, market="Hits", line="Over 0.5"):
        return {"match": "A @ B", "player": player, "market": market, "line": line}

    def test_conserva_las_legs_anteriores(self):
        guardada = {"is_parlay": True, "is_live": True, "legs": [self._leg("Judge"), self._leg("Soto")]}
        nueva = {"is_parlay": False, "is_live": False, "legs": [self._leg("Betts")]}

        fusion = merge_analyses([guardada, nueva])

        assert len(fusion["legs"]) == 3
        assert {l["player"] for l in fusion["legs"]} == {"Judge", "Soto", "Betts"}

    def test_conserva_el_estado_en_vivo(self):
        """Si la apuesta guardada era en vivo, sumarle una captura que no
        muestra la etiqueta no debe apagar el seguimiento en vivo."""
        guardada = {"is_live": True, "legs": [self._leg("Judge")]}
        nueva = {"is_live": False, "legs": [self._leg("Soto")]}

        assert merge_analyses([guardada, nueva])["is_live"] is True

    def test_mandar_la_misma_captura_dos_veces_no_duplica(self):
        guardada = {"legs": [self._leg("Judge"), self._leg("Soto")]}

        assert len(merge_analyses([guardada, guardada])["legs"]) == 2

    def test_mismo_jugador_distinto_mercado_si_se_suma(self):
        guardada = {"legs": [self._leg("Judge", market="Hits")]}
        nueva = {"legs": [self._leg("Judge", market="Home Runs")]}

        assert len(merge_analyses([guardada, nueva])["legs"]) == 2
