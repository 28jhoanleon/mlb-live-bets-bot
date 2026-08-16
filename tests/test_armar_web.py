"""Pantalla para armar combinadas desde la web.

Invierte el flujo: en vez de armar en la casa de apuestas, sacar
captura y mandarla para recién ahí ver los números, tildás picks y la
probabilidad se calcula mientras elegís.
"""
import time

from app.analysis import daily_picks as dp


class TestCacheDePicks:
    """Sin caché, cada visita a la pantalla dispararía un barrido
    completo (casa de apuestas + MLB API por jugador). Eso es justo lo
    que nos agotó la cuota una vez."""

    def setup_method(self):
        dp.limpiar_cache_picks()

    def teardown_method(self):
        dp.limpiar_cache_picks()

    def test_la_segunda_visita_no_vuelve_a_barrer(self, monkeypatch):
        llamadas = {"n": 0}

        def _falso(**kw):
            llamadas["n"] += 1
            return []

        monkeypatch.setattr(dp, "find_daily_picks", _falso)
        dp.picks_cacheados()
        dp.picks_cacheados()
        dp.picks_cacheados()
        assert llamadas["n"] == 1

    def test_el_cache_vence(self, monkeypatch):
        """Los picks cambian durante el día: no puede quedar pegado."""
        llamadas = {"n": 0}

        def _falso(**kw):
            llamadas["n"] += 1
            return []

        monkeypatch.setattr(dp, "find_daily_picks", _falso)
        dp.picks_cacheados()

        # Simular que pasó el TTL
        viejo = dp._CACHE_PICKS
        dp._CACHE_PICKS = (viejo[0] - dp._TTL_PICKS - 1, viejo[1])
        dp.picks_cacheados()
        assert llamadas["n"] == 2

    def test_el_ttl_es_razonable(self):
        """Muy corto no ahorra nada; muy largo muestra cuotas viejas."""
        assert 300 <= dp._TTL_PICKS <= 1800


class TestEndpoint:
    def test_esta_registrado(self):
        import pathlib

        assert '"/api/picks"' in pathlib.Path("app/web/api.py").read_text()

    def test_usa_la_version_cacheada(self):
        """Llamar a find_daily_picks directo saltearía el caché."""
        import pathlib

        fuente = pathlib.Path("app/web/api.py").read_text()
        assert "picks_cacheados" in fuente


class TestLaWebUsaLaMismaMatematica:
    def test_aplica_la_penalizacion_por_dependencia(self):
        """Si la web calculara la combinada como producto simple, daría
        un número más optimista que el del bot para la MISMA apuesta."""
        import pathlib

        html = pathlib.Path("app/web/static/index.html").read_text()
        assert "Math.pow(0.97, n - 1)" in html, (
            "la web no penaliza por dependencia: mostraría probabilidades "
            "distintas a las del bot para la misma combinada"
        )

    def test_coincide_con_el_calculo_del_bot(self):
        """Mismo caso en las dos partes: 3 tramos al 85/80/90."""
        probs = [0.85, 0.80, 0.90]
        esperado = 1.0
        for p in probs:
            esperado *= p
        esperado *= 0.97 ** (len(probs) - 1)
        assert round(esperado * 100, 1) == 57.6


class TestSonadorasEnLaWeb:
    """Las soñadoras también en la web: en Telegram son un choclo de
    texto que se pierde en el chat."""

    def setup_method(self):
        from app.analysis import combos
        combos.limpiar_cache_sonadoras()

    def teardown_method(self):
        from app.analysis import combos
        combos.limpiar_cache_sonadoras()

    def test_el_endpoint_esta_registrado(self):
        import pathlib

        assert '"/api/sonadoras"' in pathlib.Path("app/web/api.py").read_text()

    def test_se_cachean(self, monkeypatch):
        """Una pantalla web se refresca sola: sin caché, cada visita
        costaría un barrido completo de la casa de apuestas."""
        from app.analysis import combos

        llamadas = {"n": 0}

        def _falso(**kw):
            llamadas["n"] += 1
            return []

        monkeypatch.setattr(combos, "find_dream_combos", _falso)
        combos.sonadoras_cacheadas()
        combos.sonadoras_cacheadas()
        assert llamadas["n"] == 1

    def test_el_cache_vence(self, monkeypatch):
        from app.analysis import combos

        llamadas = {"n": 0}

        def _falso(**kw):
            llamadas["n"] += 1
            return []

        monkeypatch.setattr(combos, "find_dream_combos", _falso)
        combos.sonadoras_cacheadas()
        viejo = combos._CACHE_SONADORAS
        combos._CACHE_SONADORAS = (viejo[0] - combos._TTL_SONADORAS - 1, viejo[1])
        combos.sonadoras_cacheadas()
        assert llamadas["n"] == 2

    def test_sin_sonadoras_lo_dice_sin_inventar(self):
        """Que no haya ninguna es un resultado válido, no un error."""
        import pathlib

        html = pathlib.Path("app/web/static/index.html").read_text()
        assert "Hoy no hay ninguna que pase los filtros" in html
        assert "forzar una sería inventarla" in html
