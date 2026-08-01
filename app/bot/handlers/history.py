"""Handler de /historial: muestra las últimas apuestas/combinadas que
el bot analizó para este chat."""
from telegram import Update
from telegram.ext import ContextTypes

import json

from app.db.database import get_bet_history
from app.utils.logger import get_logger
from app.utils.telegram_helpers import escape_md

log = get_logger(__name__)


async def historial(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    rows = get_bet_history(update.effective_chat.id, limit=10)
    if not rows:
        await update.message.reply_text("Todavía no analicé ninguna apuesta tuya. Mandame una captura.")
        return

    lines = ["📜 *Últimas capturas analizadas:*\n"]
    for r in rows:
        fecha = (r.get("created_at") or "")[:16].replace("T", " ")
        resumen = r.get("match_summary") or "?"

        # Cuántas selecciones tenía, para distinguir una simple de una
        # combinada de 12 tramos de un vistazo.
        tramos = 0
        try:
            datos = json.loads(r.get("analysis_json") or "{}")
            tramos = sum(len(t.get("legs", [])) for t in datos.get("bets", []))
        except (ValueError, TypeError):
            pass

        tipo = f"{tramos} tramos" if tramos > 1 else "1 tramo" if tramos == 1 else "?"
        lines.append(f"• {fecha} — {escape_md(resumen)} — {tipo}")

    lines.append("")
    lines.append("_Para ver las soñadoras sugeridas y si se dieron:_ /combos")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
