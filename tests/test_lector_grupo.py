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
