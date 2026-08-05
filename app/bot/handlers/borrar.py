"""/borrar — saca UNA apuesta de la lista, sin tirar todo abajo.

/nueva borra todo; esto permite sacar sólo la que ya no interesa.
"""
from __future__ import annotations

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from app.db.database import borrar_ticket, get_active_bet
from app.utils.logger import get_logger
from app.utils.telegram_helpers import escape_md

log = get_logger(__name__)


async def borrar_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    actual = get_active_bet(chat_id)
    tickets = (actual or {}).get("bets", [])

    if not tickets:
        await update.message.reply_text("No tenés apuestas cargadas.")
        return

    if not context.args:
        lineas = ["*Tus apuestas:*", ""]
        for i, t in enumerate(tickets, 1):
            legs = t.get("legs", [])
            partido = legs[0].get("match", "?") if legs else "?"
            cuota = t.get("total_odds")
            extra = f" · paga {cuota}" if cuota else ""
            lineas.append(f"*{i}.* {escape_md(partido)} — {len(legs)} tramos{extra}")
        lineas.append("")
        lineas.append("Para borrar una: `/borrar 2`")
        lineas.append("Para borrar todas: /nueva")
        await update.message.reply_text("\n".join(lineas), parse_mode=ParseMode.MARKDOWN)
        return

    try:
        indice = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Decime el número. Ej: `/borrar 2`",
                                        parse_mode=ParseMode.MARKDOWN)
        return

    descripcion = borrar_ticket(chat_id, indice)
    if descripcion is None:
        await update.message.reply_text(
            f"No hay una apuesta número {indice}. Mandá /borrar para ver la lista."
        )
        return

    await update.message.reply_text(f"Borrada: {escape_md(descripcion)}",
                                    parse_mode=ParseMode.MARKDOWN)
