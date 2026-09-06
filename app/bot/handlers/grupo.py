"""Captura mensajes de un grupo o canal de picks, y arranca o extiende
el seguimiento automático a quien los mandó.

Por qué esto existe además de las reacciones
---------------------------------------------
Reaccionar depende de la API de reacciones de Telegram, que tiene
límites reales: no funciona en canales de difusión, puede fallar si la
sesión no conoce bien un chat todavía, y no siempre identifica a quien
postea como administrador anónimo. Cada uno de esos casos se fue
arreglando, pero siguen siendo puntos frágiles.

Reenviar un mensaje al bot NO tiene ninguno de esos problemas: es una
función básica de la API de bots de Telegram, funciona desde CUALQUIER
chat (grupo, canal, chat privado), y siempre trae quién lo mandó (salvo
que esa persona haya activado el reenvío anónimo, en cuyo caso Telegram
no da ese dato a nadie, ni a este bot ni a ningún otro).

Así que ahora reenviar hace lo mismo que reaccionar -- arranca o suma a
esa persona a la lista de gente seguida en ese chat -- pero por una vía
que no depende de la sesión de usuario ni de la API de reacciones.
"""
from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from app.db.database import (
    agregar_autor_a_fuente,
    agregar_fuente,
    guardar_mensaje_grupo,
    listar_fuentes,
)
from app.utils.logger import get_logger

log = get_logger(__name__)


def _normalizar_id_chat(chat_id: int) -> str:
    """Convierte un id de chat como lo da la API de bots al mismo
    formato que usa la sesión de usuario (Telethon) para ESE MISMO
    chat -- son representaciones distintas del mismo número.

    Un supergrupo o canal en la API de bots es "-100" seguido del id;
    un grupo básico es solo el id en negativo. Sin esta conversión, un
    chat sin @usuario público quedaría guardado con un id que el
    lector nunca reconoce, y el seguimiento automático no serviría de
    nada para chats privados.
    """
    texto = str(chat_id)
    if texto.startswith("-100"):
        return texto[4:]
    return texto.lstrip("-")


def _identificar(update: Update) -> tuple[str, str | None, int | None, str | None]:
    """(nombre para mostrar, nombre del autor, id del autor, handle del
    chat de origen). El handle es @usuario si el chat es público, o el
    id normalizado si no -- lo que haga falta para que el lector lo
    reconozca después."""
    msg = update.effective_message
    origen = getattr(update.effective_chat, "title", None) or "reenviado"
    autor = None
    autor_id = None
    handle = None

    reenvio = getattr(msg, "forward_origin", None)
    if reenvio is None:
        return origen, autor, autor_id, handle

    chat_origen = getattr(reenvio, "chat", None)
    if chat_origen is not None:
        origen = getattr(chat_origen, "title", None) or origen
        handle = getattr(chat_origen, "username", None)
        if not handle and getattr(chat_origen, "id", None):
            handle = _normalizar_id_chat(chat_origen.id)

    usuario = getattr(reenvio, "sender_user", None)
    if usuario is not None:
        autor = getattr(usuario, "full_name", None)
        autor_id = usuario.id
    else:
        # Admin posteando como anónimo: Telegram lo da como un chat, no
        # como usuario.
        sender_chat = getattr(reenvio, "sender_chat", None)
        if sender_chat is not None:
            autor = getattr(sender_chat, "title", None)
            autor_id = getattr(sender_chat, "id", None)
        else:
            # Privacidad de reenvío activada: solo el nombre, sin id.
            # No se puede armar seguimiento automático sin id -- se
            # guarda igual el mensaje puntual, pero no arranca nada.
            autor = getattr(reenvio, "sender_user_name", None)

    return origen, autor, autor_id, handle


def _activar_seguimiento(nombre: str, handle: str, autor: str | None, autor_id: int) -> None:
    """Arranca o extiende el seguimiento automático a esa persona en
    ese chat -- mismo mecanismo que reaccionar, otra puerta de entrada.
    """
    try:
        existente = next(
            (f for f in listar_fuentes() if f["grupo"].lower() == handle.lower()), None
        )
        if existente is None:
            agregar_fuente(
                nombre, handle, autor or "", False, False, "", "", True,
                f"{autor_id}:{autor or ''}",
            )
        else:
            agregar_autor_a_fuente(existente["grupo"], autor, autor_id)
    except Exception:
        log.exception("No pude activar el seguimiento automático")


async def capturar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    if msg is None:
        return
    texto = (msg.text or msg.caption or "").strip()
    if not texto:
        return

    origen, autor, autor_id, handle = _identificar(update)
    try:
        guardar_mensaje_grupo(origen, autor, texto)
    except Exception:
        log.exception("No pude guardar el mensaje del grupo")
        return

    log.info("Mensaje capturado de %s (%d caracteres)", origen, len(texto))

    activado = False
    if handle and autor_id is not None:
        _activar_seguimiento(origen, handle, autor, autor_id)
        activado = True

    # Confirmar solo si lo reenviaste vos: en un canal el bot no debería
    # contestar cada publicación.
    if update.channel_post is None:
        aviso = f"Guardado de *{origen}*"
        if activado:
            aviso += f"\n\nDe ahí en más sigo a *{autor or 'esa persona'}* ahí automáticamente."
        try:
            await msg.reply_text(aviso, parse_mode="Markdown")
        except Exception:
            pass
