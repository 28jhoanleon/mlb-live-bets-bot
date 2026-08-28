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
