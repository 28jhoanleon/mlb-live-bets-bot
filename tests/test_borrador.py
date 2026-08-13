"""Analizar un talón SIN haberlo apostado.

En la casa de apuestas se puede armar la combinada y ver la cuota sin
jugarla. Esa captura sirve igual, pero el bot la guardaba como apuesta
activa y la trackeaba como si tuviera plata puesta. Escribiendo
"probar" en el pie de foto se analiza y no se guarda nada.
"""
from app.bot.handlers.screenshot import _PALABRAS_BORRADOR


class TestPalabrasBorrador:
    def test_reconoce_las_variantes_esperadas(self):
        for palabra in ("probar", "borrador", "simular", "prueba", "test"):
            assert palabra in _PALABRAS_BORRADOR

    def test_una_etiqueta_normal_no_es_borrador(self):
        """Las etiquetas de agrupación ("1", "2") tienen que seguir
        funcionando como antes."""
        for etiqueta in ("1", "2", "combinada del sábado"):
            assert etiqueta.lower() not in _PALABRAS_BORRADOR


class TestNoGuardaElBorrador:
    def _analysis(self):
        from app.analysis.tickets import to_storage
        return to_storage([
            {"legs": [{"match": "A @ B", "player": "X", "market": "batter_hits",
                       "line": "Over 0.5"}], "total_odds": "1.90"},
        ])

    def test_la_firma_acepta_guardar(self):
        """El parámetro tiene que existir y venir en True por defecto:
        una captura normal se sigue guardando."""
        import inspect

        from app.bot.handlers.screenshot import _procesar_y_responder

        params = inspect.signature(_procesar_y_responder).parameters
        assert "guardar" in params
        assert params["guardar"].default is True

    def test_el_historial_solo_se_escribe_si_se_guarda(self):
        """Un borrador tampoco debe ensuciar /historial."""
        import pathlib

        fuente = pathlib.Path("app/bot/handlers/screenshot.py").read_text()
        idx_if = fuente.index("if guardar:")
        idx_log = fuente.index("log_bet_analysis(chat_id, analysis)")
        assert idx_log > idx_if, "log_bet_analysis quedó fuera del if guardar"

        # Y tiene que estar indentado DENTRO del if, no al lado.
        linea = [l for l in fuente.split("\n") if "log_bet_analysis(chat_id, analysis)" in l][0]
        sangria = len(linea) - len(linea.lstrip())
        assert sangria >= 12, f"log_bet_analysis no está dentro del if (sangría {sangria})"
