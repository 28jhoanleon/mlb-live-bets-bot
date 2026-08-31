"""Dos bugs de /mejorar reportados juntos:

1. La web no mostraba el mercado de cada tramo (aunque el bot de
   Telegram sí lo hacía) -- "3.5 → 2.5" sin decir de qué, un dato
   inútil sin contexto.
2. `sugerir_lineas` podía proponer líneas por debajo del mínimo real
   que ofrece Stake para ese mercado (por ejemplo "Over 1.5" outs de un
   abridor, cuando la casa arranca en 8.5) -- técnicamente un número,
   pero una línea que en la práctica paga casi 1.00.
"""
import pathlib

from app.analysis.lineas_stake import LINEA_MINIMA, linea_jugable


class TestLineaJugable:
    def test_debajo_del_minimo_no_es_jugable(self):
        assert not linea_jugable("pitcher_outs", 1.5)

    def test_en_o_sobre_el_minimo_si_es_jugable(self):
        assert linea_jugable("pitcher_outs", 8.5)
        assert linea_jugable("pitcher_outs", 12.5)

    def test_mercado_sin_minimo_conocido_deja_pasar_todo(self):
        assert linea_jugable("batter_hits", 0.5)

    def test_sin_punto_no_rompe(self):
        assert linea_jugable("pitcher_outs", None)

    def test_cubre_los_mercados_de_pitcheo_conocidos(self):
        for mercado in ("pitcher_strikeouts", "pitcher_hits_allowed",
                        "pitcher_earned_runs", "pitcher_outs", "pitcher_walks"):
            assert mercado in LINEA_MINIMA


class TestSugerirLineasRespetaElMinimo:
    def test_no_propone_nada_por_debajo_del_minimo_real(self):
        from unittest.mock import patch

        from app.analysis.probability import sugerir_lineas

        juegos = [{"outs": v} for v in [18, 21, 15, 18, 19, 20, 17]]
        jugador = {"id": 1, "team": "X"}

        with patch("app.analysis.probability._buscar_jugador_cacheado", return_value=jugador), \
             patch("app.analysis.probability._cargar_jugador_y_partidos",
                   return_value=(jugador, "Over", 15.5, True, ["outs"], juegos)):
            opciones = sugerir_lineas("Pitcher X", "pitcher_outs", "Over 15.5")

        assert all(o.linea >= 8.5 for o in opciones)

    def test_la_linea_apostada_se_mantiene_aunque_sea_baja(self):
        """No es una sugerencia, es un hecho: se apostó y listo. El
        filtro es solo para lo que el bot propone de más."""
        from unittest.mock import patch

        from app.analysis.probability import sugerir_lineas

        juegos = [{"outs": v} for v in [18, 21, 15, 18, 19, 20, 17]]
        jugador = {"id": 1, "team": "X"}

        with patch("app.analysis.probability._buscar_jugador_cacheado", return_value=jugador), \
             patch("app.analysis.probability._cargar_jugador_y_partidos",
                   return_value=(jugador, "Over", 3.5, True, ["outs"], juegos)):
            opciones = sugerir_lineas("Pitcher X", "pitcher_outs", "Over 3.5")

        apostada = next(o for o in opciones if o.es_la_apostada)
        assert apostada.linea == 3.5


class TestDailyPicksUsaElMismoModulo:
    """daily_picks.py tenía su propia copia del diccionario; ahora usa
    el módulo compartido, para que un ajuste futuro no haya que
    hacerlo en dos lugares."""

    def test_ya_no_tiene_su_propia_copia(self):
        fuente = pathlib.Path("app/analysis/daily_picks.py").read_text()
        assert "from app.analysis.lineas_stake import" in fuente

    def test_sigue_funcionando_igual(self):
        from app.analysis.daily_picks import _linea_existe

        assert not _linea_existe("pitcher_outs", 1.5)
        assert _linea_existe("pitcher_outs", 8.5)


class TestLaWebMuestraElMercado:
    def test_el_html_incluye_el_mercado_en_las_tres_ramas(self):
        html = pathlib.Path("app/web/static/index.html").read_text()
        i = html.index("const filas = tramos.map(t => {")
        j = html.index("}).join('');", i)
        bloque = html[i:j]
        assert bloque.count("${mercado}") == 3

    def test_el_bot_de_telegram_ya_lo_mostraba(self):
        """Confirmación de que el hueco era solo de la web."""
        fuente = pathlib.Path("app/bot/handlers/mejorar.py").read_text()
        assert "nombre_stake_texto(t.market)" in fuente
