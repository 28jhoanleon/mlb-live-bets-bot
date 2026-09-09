"""Captura mensajes de un grupo o canal de picks, y arranca o extiende
el seguimiento automático a quien los mandó.

Por qué esto existe además de las reacciones
---------------------------------------------
Reaccionar depende de la API de reacciones de Telegram, que tiene
límites reales: no funciona en canales de difusión, puede fallar si la
sesión no conoce bien un chat todavía, y no siempre identifica a quien
postea como administrador anónimo. Cada uno de esos casos se fue
arreglando, pero siguen siendo puntos frágiles.

Reenviar tiene su propia limitación, distinta y más dura: cuando
reenviás el mensaje de una persona común (el caso más frecuente, ni
canal ni admin anónimo), la API de bots de Telegram directamente NO le
da al bot ningún dato de EN QUÉ CHAT estaba ese mensaje -- por
privacidad, solo entrega quién lo mandó. No hay forma de rodear esto
con código: es una decisión de diseño de Telegram.

La solución: en ese caso se sigue a la persona con el comodín "*" (ver
GRUPO_COMODIN), que significa "en cualquier chat donde la sesión la
vea". Es, de hecho, mejor que atarlo a un solo grupo -- es lo que en
realidad se pidió: seguir a alguien sea de donde sea el contenido.
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


GRUPO_COMODIN = "*"  # "cualquier chat" -- ver _es_el_grupo en app.lector.cliente


def _identificar(update: Update) -> tuple[str, str | None, int | None, str | None]:
    """(nombre para mostrar, nombre del autor, id del autor, handle del
    chat de origen).

    El handle sale así, en orden de preferencia:
    - @usuario si el chat de origen es público
    - el id normalizado si no, pero SOLO se conoce cuando el mensaje
      viene de un canal o de un admin posteando como anónimo -- son los
      dos únicos casos donde Telegram le da esa info al bot
    - el comodín "*" en el caso más común de todos: alguien común
      reenviando un mensaje de otra persona común. Ahí la API de bots
      NO expone en qué chat estaba -- ver el módulo docstring.
    """
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
        if handle is None:
            # El caso común: persona reenviando de una persona. Sin
            # dato del chat, se sigue a la persona en cualquier lado.
            handle = GRUPO_COMODIN
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
        nombre_fuente = "Seguidos por reenvío (cualquier chat)" if handle == GRUPO_COMODIN else origen
        _activar_seguimiento(nombre_fuente, handle, autor, autor_id)
        activado = True

    # Confirmar solo si lo reenviaste vos: en un canal el bot no debería
    # contestar cada publicación.
    if update.channel_post is None:
        aviso = f"Guardado de *{origen}*"
        if activado:
            donde = "en cualquier chat" if handle == GRUPO_COMODIN else "ahí"
            aviso += f"\n\nDe ahí en más sigo a *{autor or 'esa persona'}* {donde} automáticamente."
        try:
            await msg.reply_text(aviso, parse_mode="Markdown")
        except Exception:
            pass
