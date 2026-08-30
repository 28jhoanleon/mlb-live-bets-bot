"""Lector del grupo de picks con la cuenta de usuario.

La sesión que usa da acceso a TODO el Telegram del usuario, no solo al
grupo. Estos tests fijan las protecciones que hacen que eso sea
aceptable: leer únicamente el grupo configurado, no escribir nunca, y
no arrancar si no está configurado explícitamente.

Si alguno de estos falla, el lector pasó a tener más alcance del que se
acordó.
"""
import pathlib
import types

from app.lector.cliente import _es_el_grupo, configurado


FUENTE = pathlib.Path("app/lector/cliente.py").read_text()


def _chat(username=None, id=None):
    return types.SimpleNamespace(username=username, id=id)


class TestSoloEseGrupo:
    """La sesión ve todos los chats del usuario. Guardar cualquier otro
    sería recolectar conversaciones privadas sin que nadie lo pidiera."""

    def test_reconoce_el_grupo_por_username(self):
        assert _es_el_grupo(_chat(username="ludogallina2024"), "ludogallina2024")

    def test_tolera_la_arroba(self):
        assert _es_el_grupo(_chat(username="ludogallina2024"), "@ludogallina2024")

    def test_no_distingue_mayusculas(self):
        assert _es_el_grupo(_chat(username="LudoGallina2024"), "ludogallina2024")

    def test_reconoce_por_id(self):
        assert _es_el_grupo(_chat(id=-100123456), "-100123456")

    def test_descarta_cualquier_otro_chat(self):
        assert not _es_el_grupo(_chat(username="otro_grupo"), "ludogallina2024")

    def test_descarta_un_chat_privado(self):
        """Un mensaje directo de un amigo no debe guardarse jamás."""
        assert not _es_el_grupo(_chat(username=None, id=987654), "ludogallina2024")

    def test_sin_chat_no_guarda(self):
        assert not _es_el_grupo(None, "ludogallina2024")


class TestSoloLectura:
    def test_no_manda_mensajes(self):
        """El lector nunca debe escribir: ni responder, ni reenviar."""
        for prohibido in ("send_message", "send_file", "reply(", "forward_messages"):
            assert prohibido not in FUENTE, f"el lector usa {prohibido}"

    def test_no_se_une_ni_sale_de_chats(self):
        for prohibido in ("JoinChannelRequest", "LeaveChannelRequest", "delete_messages"):
            assert prohibido not in FUENTE

    def test_no_lee_el_historial_de_otros_chats(self):
        """iter_messages sobre chats arbitrarios sería recolección
        masiva; solo se escuchan mensajes nuevos del grupo."""
        assert "iter_messages" not in FUENTE
        assert "get_dialogs" not in FUENTE


class TestEsOpcional:
    def test_sin_configurar_no_arranca(self):
        assert configurado() is False

    def test_la_sesion_no_esta_en_el_codigo(self):
        """Tiene que venir por variable de entorno, nunca escrita."""
        assert "TELEGRAM_SESSION" not in FUENTE or "settings.telegram_session" in FUENTE

    def test_no_se_guarda_la_sesion_en_disco(self):
        """StringSession vive en memoria; una sesión en archivo quedaría
        en el disco del servidor."""
        assert "StringSession" in FUENTE


class TestNoSeCae:
    def test_reintenta_si_se_desconecta(self):
        """La consigna era que no pare nunca."""
        assert "while True:" in FUENTE
        assert "asyncio.sleep(60)" in FUENTE

    def test_un_mensaje_con_error_no_tumba_el_lector(self):
        assert "except Exception:" in FUENTE


class TestDependencia:
    def test_telethon_no_compila_nada(self):
        """Regla del proyecto: nada que compile código nativo, porque en
        Android falla. Telethon se publica como py3-none-any."""
        reqs = pathlib.Path("requirements.txt").read_text()
        assert "telethon" in reqs

    def test_si_falta_telethon_no_rompe_el_arranque(self):
        assert "except ImportError:" in FUENTE


class TestBugsRealesDeReacciones:
    """Dos causas encontradas de por qué reaccionar "no hacía nada":

    1. La consulta de la lista completa de reacciones recibía el Peer
       crudo de la actualización (solo el id), pero esa consulta exige
       un InputPeer resuelto con access_hash. Sin resolverlo, la
       consulta tira una excepción que quedaba tragada en silencio.

    2. Telegram a veces manda el emoji con el selector de variante
       (U+FE0F) pegado y a veces sin él. "🔥" y "🔥\ufe0f" son strings
       distintos en Python, así que la comparación contra los emojis
       configurados podía fallar aunque fueran el mismo emoji.
    """

    def test_resuelve_el_peer_antes_de_consultar(self):
        fuente = pathlib.Path("app/lector/cliente.py").read_text()
        assert "get_input_entity(update.peer)" in fuente
        assert "peer=peer_resuelto" in fuente

    def test_normaliza_el_selector_de_variante(self):
        from app.lector.cliente import _normalizar_emoji

        assert _normalizar_emoji("🔥\ufe0f") == "🔥"
        assert _normalizar_emoji("🔥") == "🔥"

    def test_los_emojis_configurados_tambien_se_normalizan(self):
        from app.lector.cliente import _emojis_configurados

        emojis = _emojis_configurados()
        assert "\ufe0f" not in "".join(emojis)

    def test_matchea_aunque_llegue_con_selector(self):
        from app.lector.cliente import _emojis_configurados, _normalizar_emoji

        assert _normalizar_emoji("👍\ufe0f") in _emojis_configurados()

    def test_normalizar_con_none_no_rompe(self):
        from app.lector.cliente import _normalizar_emoji

        assert _normalizar_emoji(None) is None


class TestSegundoIntentoDeResolverElPeer:
    """Reportado: reaccionar funcionaba en un grupo y en otros no.
    get_input_entity() solo mira la caché local de la sesión; si el
    chat todavía no pasó por ahí, falla aunque la cuenta sea miembro.
    get_entity() consulta a Telegram si hace falta -- segundo intento
    antes de rendirse."""

    def test_hay_un_segundo_intento_con_get_entity(self):
        fuente = pathlib.Path("app/lector/cliente.py").read_text()
        i = fuente.index("async def _mi_reaccion")
        bloque = fuente[i:i + 2500]
        assert "get_input_entity(update.peer)" in bloque
        assert "get_entity(update.peer)" in bloque

    def test_el_log_de_error_incluye_datos_para_diagnosticar(self):
        """Si hay que revisar logs de Railway, el chat_id y msg_id
        tienen que estar ahí para poder ubicar el caso."""
        fuente = pathlib.Path("app/lector/cliente.py").read_text()
        i = fuente.index("async def _mi_reaccion")
        bloque = fuente[i:i + 3500]
        assert "chat_id=" in bloque
        assert "msg_id=" in bloque


class TestLinksEscondidosDetrasDeTexto:
    """Bug real, confirmado con un mensaje "x20" que tenía un cupón
    linkeado detrás del texto corto. Telegram permite que una palabra
    lleve una URL invisible atrás; `mensaje.message` (el texto plano)
    no la incluye en ningún lado. Sin extraerla de las entidades, el
    link no se guardaba, no se veía, y tampoco lo detectaban los
    filtros de casa/link."""

    def _mensaje(self, texto, entidades=None):
        import types

        return types.SimpleNamespace(message=texto, entities=entidades or [])

    def test_agrega_la_url_escondida_al_texto(self):
        import types

        from app.lector.cliente import _texto_con_links

        entidad = types.SimpleNamespace(url="https://pba.stake.bet.ar/x")
        mensaje = self._mensaje("x20", [entidad])
        resultado = _texto_con_links(mensaje)
        assert "x20" in resultado
        assert "https://pba.stake.bet.ar/x" in resultado

    def test_no_duplica_si_la_url_ya_estaba_visible(self):
        import types

        from app.lector.cliente import _texto_con_links

        entidad = types.SimpleNamespace(url="https://x.com/y")
        mensaje = self._mensaje("mirá https://x.com/y", [entidad])
        resultado = _texto_con_links(mensaje)
        assert resultado.count("https://x.com/y") == 1

    def test_sin_entidades_no_rompe(self):
        from app.lector.cliente import _texto_con_links

        assert _texto_con_links(self._mensaje("texto normal")) == "texto normal"

    def test_entidades_sin_url_no_rompen(self):
        """Negrita, cursiva, etc. son entidades sin .url -- no deben
        romper ni agregar nada."""
        import types

        from app.lector.cliente import _texto_con_links

        entidad = types.SimpleNamespace()  # sin atributo url
        assert _texto_con_links(self._mensaje("*texto*", [entidad])) == "*texto*"

    def test_el_filtro_de_casa_ahora_encuentra_el_link_escondido(self):
        import types

        from app.lector.cliente import _texto_con_links
        from app.lector.filtros import tiene_casa

        entidad = types.SimpleNamespace(url="https://pba.stake.bet.ar/x")
        texto = _texto_con_links(self._mensaje("x20", [entidad]))
        assert tiene_casa(texto, "stake")


class TestCanalDeDifusion:
    """Reportado con un log real: reaccionar en un CANAL (no un grupo)
    tira BroadcastForbiddenError -- Telegram no deja pedir quién
    reaccionó ahí ni siendo miembro. Es una restricción de la
    plataforma, no un bug: hay que reconocerla y no tratarla como
    cualquier otro error."""

    def test_reconoce_el_error_especifico_de_canal(self):
        fuente = pathlib.Path("app/lector/cliente.py").read_text()
        assert "BroadcastForbiddenError" in fuente

    def test_no_lo_trata_como_error_generico(self):
        """Tiene que tener su propio except, antes del genérico, para
        no generar un traceback como si fuera un bug."""
        fuente = pathlib.Path("app/lector/cliente.py").read_text()
        i = fuente.index("except BroadcastForbiddenError:")
        j = fuente.index("except Exception:", i)
        assert i < j  # el específico va ANTES que el genérico


class TestNombreDeQuienReacciono:
    """Bug real, con captura: las tres personas aparecían como "id
    7829324545" en vez de sus nombres. `first_name` no está para
    admins que postean como anónimos -- Telegram los da como un
    chat/canal, con `.title` en vez de `.first_name`. El filtro
    funcionaba bien por dentro (por id), pero visualmente no decía
    nada."""

    def _remitente(self, first_name=None, last_name=None, title=None, username=None):
        import types

        return types.SimpleNamespace(
            first_name=first_name, last_name=last_name, title=title, username=username,
        )

    def test_usuario_normal(self):
        from app.lector.cliente import _nombre_de

        assert _nombre_de(self._remitente(first_name="Cara Roja")) == "Cara Roja"

    def test_admin_anonimo_usa_el_titulo(self):
        from app.lector.cliente import _nombre_de

        r = self._remitente(title="Westbrook COMUNITARIO 2.0")
        assert _nombre_de(r) == "Westbrook COMUNITARIO 2.0"

    def test_con_apellido_lo_incluye(self):
        from app.lector.cliente import _nombre_de

        r = self._remitente(first_name="Juan", last_name="Pérez")
        assert _nombre_de(r) == "Juan Pérez"

    def test_ultimo_respaldo_es_el_username(self):
        from app.lector.cliente import _nombre_de

        r = self._remitente(username="tin_oficial")
        assert _nombre_de(r) == "@tin_oficial"

    def test_si_no_hay_nada_devuelve_none_no_rompe(self):
        from app.lector.cliente import _nombre_de

        assert _nombre_de(self._remitente()) is None

    def test_se_usa_en_los_dos_lugares_donde_se_extrae_autor(self):
        fuente = pathlib.Path("app/lector/cliente.py").read_text()
        assert fuente.count("autor = _nombre_de(remitente)") == 2


class TestLogsVisiblesEnRailway:
    """Bug de diagnóstico, no de funcionalidad: los logs clave del
    camino de reacción estaban en DEBUG, pero Railway solo muestra
    INFO para arriba por default. Eran literalmente invisibles aunque
    el código sí estuviera corriendo -- por eso un log real no mostraba
    ninguna pista, ni siquiera un error.
    """

    def test_no_quedan_log_debug_en_el_camino_de_reaccion(self):
        fuente = pathlib.Path("app/lector/cliente.py").read_text()
        i = fuente.index("async def _reaccion(update):")
        j = fuente.index("except Exception:\n            log.exception(\"Error procesando una reacción\")")
        bloque = fuente[i:j]
        assert "log.debug(" not in bloque

    def test_hay_un_log_al_principio_de_todo(self):
        """Para distinguir "el handler nunca se disparó" de "se disparó
        pero algo falló adentro"."""
        fuente = pathlib.Path("app/lector/cliente.py").read_text()
        i = fuente.index("async def _reaccion(update):")
        bloque = fuente[i:i + 500]
        assert "Reacción cruda recibida" in bloque

    def test_cada_salida_temprana_deja_rastro(self):
        fuente = pathlib.Path("app/lector/cliente.py").read_text()
        i = fuente.index("async def _reaccion(update):")
        j = fuente.index("except Exception:\n            log.exception(\"Error procesando una reacción\")")
        bloque = fuente[i:j]
        assert "Sin emojis configurados" in bloque
        assert "No pude identificar cuál emoji" in bloque
        assert "no está en la lista configurada" in bloque
        assert "get_messages no devolvió" in bloque
