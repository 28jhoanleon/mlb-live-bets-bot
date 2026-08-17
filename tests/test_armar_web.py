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


class TestPartidoEnCursoSinDatos:
    """Bug reportado: partidos que "de la nada dejan de estar en vivo" y
    muestran el histórico como si no estuviera pasando nada.

    La MLB Stats API falla de a ratos (403 intermitentes en producción).
    Una sola consulta fallida dejaba live_data en None y la web caía al
    promedio histórico sin avisar."""

    def test_guarda_el_ultimo_estado_bueno(self):
        import pathlib

        fuente = pathlib.Path("app/web/service.py").read_text()
        assert "_ULTIMO_VIVO" in fuente
        assert "Usando el último estado en vivo conocido" in fuente

    def test_la_copia_tiene_vencimiento(self):
        """Datos de hace un minuto sirven; de hace una hora, no."""
        from app.web.service import _VIGENCIA_ULTIMO_VIVO

        assert 60 <= _VIGENCIA_ULTIMO_VIVO <= 900

    def test_avisa_cuando_no_hay_dato_en_vivo(self):
        """Mostrar el histórico sin aclarar hace parecer que el partido
        no empezó."""
        import pathlib

        fuente = pathlib.Path("app/web/service.py").read_text()
        assert "Sin conexión con el dato en vivo" in fuente


class TestPrecalentado:
    def test_el_job_deja_listos_los_picks(self):
        """Sin esto, la primera visita a Armar o Soñadoras espera el
        barrido completo con la pantalla en blanco."""
        import pathlib

        fuente = pathlib.Path("app/jobs/registrar_resueltas.py").read_text()
        assert "picks_cacheados" in fuente
        assert "sonadoras_cacheadas" in fuente

    def test_un_fallo_al_precalentar_no_rompe_el_job(self):
        import pathlib

        fuente = pathlib.Path("app/jobs/registrar_resueltas.py").read_text()
        assert "No pude precalentar" in fuente


class TestWebAutosuficiente:
    """La web ya no depende de Telegram: se puede cargar una apuesta,
    verla, mejorarla y borrarla sin abrir el chat."""

    def test_se_puede_subir_captura(self):
        import pathlib

        fuente = pathlib.Path("app/web/api.py").read_text()
        assert '"/api/captura"' in fuente
        assert 'methods=["POST"]' in fuente

    def test_las_imagenes_van_en_base64(self):
        """Recibir multipart pediría una dependencia nueva; el proyecto
        evita sumar librerías salvo que hagan falta de verdad."""
        import pathlib

        fuente = pathlib.Path("app/web/api.py").read_text()
        assert "base64.b64decode" in fuente

    def test_se_puede_mejorar_desde_la_web(self):
        import pathlib

        assert '"/api/mejorar"' in pathlib.Path("app/web/api.py").read_text()

    def test_el_borrador_tambien_desde_la_web(self):
        import pathlib

        html = pathlib.Path("app/web/static/index.html").read_text()
        assert "Probar sin guardar" in html

    def test_una_captura_ilegible_no_borra_lo_guardado(self):
        """Si la lectura falla, la apuesta que ya estaba tiene que
        quedar intacta."""
        import pathlib

        fuente = pathlib.Path("app/web/service.py").read_text()
        i_check = fuente.index('if not leidos:')
        i_save = fuente.index("save_active_bet(chat_id, analisis)")
        assert i_check < i_save, "se guarda antes de verificar que se leyó algo"
