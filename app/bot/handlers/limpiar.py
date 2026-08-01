"""/limpiar — borra los resultados calculados con la versión con bugs.

Los combos resueltos antes del arreglo quedaron con un resultado
equivocado guardado (marcaba "se dio" combos perdidos). El código sólo
resuelve los que están sin resolver, así que hay que vaciar esos
resultados para que se recalculen bien.

No borra los combos ni el historial: sólo los veredictos.
"""
from __future__ import annotations

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from app.db.database import limpiar_legs_resueltas, limpiar_resultados_combos
from app.utils.logger import get_logger

log = get_logger(__name__)


async def limpiar_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id

    if not context.args or context.args[0].lower() != "si":
        await update.message.reply_text(
            "Esto borra los *resultados* calculados de tus soñadoras y los "
            "datos de calibración, para que se recalculen sin el bug que "
            "marcaba como ganados combos perdidos.\n\n"
            "Los combos y el historial NO se borran.\n\n"
            "Si estás seguro, mandá: `/limpiar si`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    combos = limpiar_resultados_combos(chat_id)
    legs = limpiar_legs_resueltas(chat_id)

    await update.message.reply_text(
        f"Listo.\n\n"
        f"• Resultados de combos borrados: *{combos}*\n"
        f"• Legs de calibración borradas: *{legs}*\n\n"
        f"Se van a recalcular solos la próxima vez que uses /historial.",
        parse_mode=ParseMode.MARKDOWN,
    )
