"""Handler de /miid: muestra el chat ID.

Hace falta para configurar la web: el servidor necesita saber de qué
usuario mostrar las apuestas (OWNER_CHAT_ID).
"""
from telegram import Update
from telegram.ext import ContextTypes


async def miid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    await update.message.reply_text(
        f"Tu chat ID es `{chat_id}`\n\n"
        "Cargalo en Railway como *OWNER\\_CHAT\\_ID* para que la web muestre "
        "tus apuestas.",
        parse_mode="Markdown",
    )
