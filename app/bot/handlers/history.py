"""Handler de /historial: muestra las últimas apuestas/combinadas que
el bot analizó para este chat."""
from telegram import Update
from telegram.ext import ContextTypes

from app.db.database import get_bet_history
from app.utils.logger import get_logger

log = get_logger(__name__)


async def historial(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    rows = get_bet_history(update.effective_chat.id, limit=10)
    if not rows:
        await update.message.reply_text("Todavía no analicé ninguna apuesta tuya. Mandame una captura.")
        return

    lines = ["📜 *Últimas apuestas analizadas:*\n"]
    for r in rows:
        tipo = "Combinada" if r.get("is_parlay") else "Apuesta simple"
        fecha = (r.get("created_at") or "")[:16].replace("T", " ")
        lines.append(f"• {fecha} — {tipo} — {r.get('match_summary', '?')}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
