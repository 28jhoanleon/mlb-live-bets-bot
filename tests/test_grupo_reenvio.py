"""Reenviar un mensaje al bot arranca el mismo seguimiento automático
que reaccionar, pero por una vía que no depende de la sesión de
usuario ni de la frágil API de reacciones de Telegram: funciona desde
CUALQUIER chat, sin importar si es grupo, canal, o si la sesión ya
"conoce" ese chat.
"""
import types

import pytest

from app.bot.handlers.grupo import _identificar, _normalizar_id_chat
from app.db import database


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/g.db")
    monkeypatch.setattr(database, "_db_path", lambda: str(tmp_path / "g.db"))
    database.init_db()
    return database


def _update_reenviado(chat_username=None, chat_id=None, chat_title="Grupo Test",
                       sender_id=111, sender_name="Cara Roja", sender_chat=None,
                       nombre_oculto=None):
    chat_origen = types.SimpleNamespace(
        title=chat_title, username=chat_username, id=chat_id,
    )
    usuario = None
    if sender_name and sender_chat is None and nombre_oculto is None:
        usuario = types.SimpleNamespace(id=sender_id, full_name=sender_name)

    reenvio = types.SimpleNamespace(
        chat=chat_origen, sender_user=usuario,
        sender_chat=sender_chat, sender_user_name=nombre_oculto,
    )
    msg = types.SimpleNamespace(forward_origin=reenvio, text="un pick", caption=None)
    chat_actual = types.SimpleNamespace(title=None)
    return types.SimpleNamespace(effective_message=msg, effective_chat=chat_actual,
                                  channel_post=None)


class TestNormalizarId:
    def test_supergrupo_o_canal(self):
        assert _normalizar_id_chat(-1001234567890) == "1234567890"

    def test_grupo_basico(self):
        assert _normalizar_id_chat(-123456789) == "123456789"


class TestIdentificar:
    def test_grupo_publico_usa_el_username(self):
        u = _update_reenviado(chat_username="ludogallina2024")
        _, autor, autor_id, handle = _identificar(u)
        assert handle == "ludogallina2024"
        assert autor == "Cara Roja"
        assert autor_id == 111

    def test_grupo_privado_usa_el_id_normalizado(self):
        u = _update_reenviado(chat_username=None, chat_id=-1009876543210)
        _, _, _, handle = _identificar(u)
        assert handle == "9876543210"

    def test_admin_anonimo_usa_el_sender_chat(self):
        anonimo = types.SimpleNamespace(title="Westbrook COMUNITARIO 2.0", id=555)
        u = _update_reenviado(sender_name=None, sender_chat=anonimo)
        _, autor, autor_id, _ = _identificar(u)
        assert autor == "Westbrook COMUNITARIO 2.0"
        assert autor_id == 555

    def test_reenvio_anonimo_no_da_id(self):
        """Si la persona activó "reenviar sin remitente", Telegram no
        da el id a nadie. Se guarda el nombre, sin poder armar
        seguimiento automático."""
        u = _update_reenviado(sender_name=None, nombre_oculto="Alguien")
        _, autor, autor_id, _ = _identificar(u)
        assert autor == "Alguien"
        assert autor_id is None


class _AsyncMock:
    def __init__(self):
        self.call_args = None

    async def __call__(self, *args, **kwargs):
        from unittest.mock import call

        self.call_args = call(*args, **kwargs)


class TestCapturarActivaElSeguimiento:
    """Sin plugin de pytest-asyncio instalado -- se corre con
    asyncio.run directo, como ya conviene para no sumar una
    dependencia nueva solo para los tests."""

    def test_primera_vez_crea_la_fuente(self, db):
        import asyncio

        from app.bot.handlers.grupo import capturar

        u = _update_reenviado(chat_username="ludogallina2024")
        u.effective_message.reply_text = _AsyncMock()

        asyncio.run(capturar(u, None))

        fuentes = db.listar_fuentes()
        assert len(fuentes) == 1
        assert fuentes[0]["grupo"] == "ludogallina2024"
        assert "Cara Roja" in fuentes[0]["autores"]
        assert fuentes[0]["solo_apuestas"] == 1

    def test_segunda_persona_se_suma_a_la_misma_fuente(self, db):
        import asyncio

        from app.bot.handlers.grupo import capturar

        u1 = _update_reenviado(chat_username="g1", sender_id=111, sender_name="Cara Roja")
        u1.effective_message.reply_text = _AsyncMock()
        asyncio.run(capturar(u1, None))

        u2 = _update_reenviado(chat_username="g1", sender_id=222, sender_name="leandro")
        u2.effective_message.reply_text = _AsyncMock()
        asyncio.run(capturar(u2, None))

        fuentes = db.listar_fuentes()
        assert len(fuentes) == 1
        assert "Cara Roja" in fuentes[0]["autores"]
        assert "leandro" in fuentes[0]["autores"]

    def test_sin_id_no_arma_seguimiento_pero_guarda_el_mensaje(self, db):
        import asyncio

        from app.bot.handlers.grupo import capturar

        u = _update_reenviado(sender_name=None, nombre_oculto="Alguien",
                              chat_username="g1")
        u.effective_message.reply_text = _AsyncMock()

        asyncio.run(capturar(u, None))

        assert db.listar_fuentes() == []
        assert len(db.leer_mensajes_grupo()) == 1

    def test_avisa_cuando_activa_el_seguimiento(self, db):
        import asyncio

        from app.bot.handlers.grupo import capturar

        u = _update_reenviado(chat_username="g1")
        u.effective_message.reply_text = _AsyncMock()

        asyncio.run(capturar(u, None))

        texto_aviso = u.effective_message.reply_text.call_args.args[0]
        assert "sigo a" in texto_aviso.lower()


class TestComodinCuandoNoHayDatoDelChat:
    """El descubrimiento clave: cuando reenviás el mensaje de una
    persona común (no canal, no admin anónimo), la API de bots de
    Telegram NO le da al bot ningún dato de en qué chat estaba ese
    mensaje. Es privacidad de Telegram, no algo que se pueda evitar.

    La solución: seguir a esa persona con el comodín "*" -- en
    cualquier chat donde la sesión la vea -- que además es justo lo
    que se pidió ("seguir sea de donde sea el contenido")."""

    def test_persona_comun_sin_chat_usa_el_comodin(self):
        u = _update_reenviado(chat_username=None, chat_id=None)
        _, _, _, handle = _identificar(u)
        assert handle == "*"

    def test_canal_o_admin_anonimo_sigue_usando_el_chat_real(self):
        """Cuando SÍ hay dato del chat (porque es canal o admin
        anónimo), no hace falta el comodín -- es más preciso atarlo al
        chat real."""
        u = _update_reenviado(chat_username="ludogallina2024")
        _, _, _, handle = _identificar(u)
        assert handle == "ludogallina2024"

    def test_capturar_crea_la_fuente_comodin(self, db):
        import asyncio

        from app.bot.handlers.grupo import capturar

        u = _update_reenviado(chat_username=None, chat_id=None)
        u.effective_message.reply_text = _AsyncMock()

        asyncio.run(capturar(u, None))

        fuentes = db.listar_fuentes()
        assert len(fuentes) == 1
        assert fuentes[0]["grupo"] == "*"

    def test_el_lector_reconoce_el_comodin_como_cualquier_chat(self):
        from app.lector.cliente import _es_el_grupo

        assert _es_el_grupo(None, "*") is True

        import types

        cualquier_chat = types.SimpleNamespace(username="lo-que-sea", id=999)
        assert _es_el_grupo(cualquier_chat, "*") is True

    def test_el_mensaje_capturado_por_comodin_conserva_el_chat_real(self):
        """Aunque la fuente sea el comodín, el mensaje guardado tiene
        que decir de qué chat vino de verdad -- si no, todo lo
        capturado por reenvío se ve igual sin importar el origen."""
        import pathlib

        fuente = pathlib.Path("app/lector/cliente.py").read_text()
        assert 'fuente["grupo"] == "*"' in fuente
        assert "getattr(chat, \"title\", None) or fuente[\"nombre\"]" in fuente


class TestDiagnosticoCompleto:
    """El log real que se recibió mostraba que el mensaje SÍ se
    guardó, pero no había ningún rastro de si el seguimiento se activó
    o no -- faltaba el log, no la lógica. Con esto, el próximo log va
    a decir la verdad completa en un solo vistazo."""

    def test_hay_log_de_diagnostico_despues_de_identificar(self):
        import pathlib

        fuente = pathlib.Path("app/bot/handlers/grupo.py").read_text()
        assert "Identificado: autor=" in fuente

    def test_confirma_cuando_crea_fuente_nueva(self):
        import pathlib

        fuente = pathlib.Path("app/bot/handlers/grupo.py").read_text()
        i = fuente.index("def _activar_seguimiento")
        bloque = fuente[i:i + 900]
        assert "Fuente nueva creada" in bloque

    def test_confirma_cuando_suma_a_una_existente(self):
        import pathlib

        fuente = pathlib.Path("app/bot/handlers/grupo.py").read_text()
        i = fuente.index("def _activar_seguimiento")
        bloque = fuente[i:i + 900]
        assert "sumado a la fuente existente" in bloque

    def test_avisa_cuando_es_privacidad_del_remitente_original(self):
        """Caso distinto a todos los anteriores: si quien ESCRIBIÓ el
        mensaje original tiene reenvíos restringidos en su privacidad,
        Telegram oculta su id a cualquiera que reenvíe -- no hay forma
        de sortear esto con código."""
        import pathlib

        fuente = pathlib.Path("app/bot/handlers/grupo.py").read_text()
        assert "privacidad de esa" in fuente.lower() or "privacidad de la persona" in fuente.lower()
