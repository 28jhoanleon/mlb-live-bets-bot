"""Captura mensajes de un grupo o canal de picks.

Las reglas de Telegram que mandan acá, y que no se pueden sortear:

- Un bot NO puede leer un grupo del que no forma parte.
- Un bot NO puede recibir mensajes de otro bot.

Las dos vías que sí funcionan:

1. Reenviarle el mensaje al bot a mano (siempre funciona).
2. Poner al bot como ADMINISTRADOR de un canal propio y publicar ahí.
   El bot recibe las publicaciones del canal aunque no las escriba él.

Este módulo acepta las dos, así se puede probar cuál sirve.
"""
from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from app.db.database import guardar_mensaje_grupo
from app.utils.logger import get_logger

log = get_logger(__name__)


def _origen_de(update: Update) -> tuple[str, str | None]:
    """De dónde vino y quién lo escribió originalmente."""
    msg = update.effective_message
    origen = getattr(update.effective_chat, "title", None) or "reenviado"
    autor = None

    # Telegram conserva el origen de un reenvío si la privacidad del
    # autor lo permite; si no, viene anónimo y no hay nada que hacer.
    reenvio = getattr(msg, "forward_origin", None)
    if reenvio is not None:
        origen = (
            getattr(getattr(reenvio, "chat", None), "title", None)
            or getattr(reenvio, "sender_user_name", None)
            or origen
        )
        usuario = getattr(reenvio, "sender_user", None)
        if usuario is not None:
            autor = getattr(usuario, "full_name", None)

    return origen, autor


async def capturar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    if msg is None:
        return
    texto = (msg.text or msg.caption or "").strip()
    if not texto:
        return

    origen, autor = _origen_de(update)
    try:
        guardar_mensaje_grupo(origen, autor, texto)
    except Exception:
        log.exception("No pude guardar el mensaje del grupo")
        return

    log.info("Mensaje capturado de %s (%d caracteres)", origen, len(texto))

    # Confirmar solo si lo reenviaste vos: en un canal el bot no debería
    # contestar cada publicación.
    if update.channel_post is None:
        try:
            await msg.reply_text(f"Guardado de *{origen}*", parse_mode="Markdown")
        except Exception:
            pass
