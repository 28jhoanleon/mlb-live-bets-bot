"""Handler de /analyze: los mejores picks del día, calculados cruzando
nuestra propia probabilidad (últimos partidos reales del jugador) con
la cuota de mercado — no una simple lista de props."""
from telegram import Update
from telegram.ext import ContextTypes

from app.analysis.daily_picks import confidence_stars, find_daily_picks
from app.utils.logger import get_logger
from app.utils.telegram_helpers import escape_md

log = get_logger(__name__)


async def analyze(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    processing_msg = await update.message.reply_text("🔍 Analizando props del día contra el historial de cada jugador...")

    try:
        picks = find_daily_picks(max_events=5)
    except Exception:
        log.exception("Error buscando picks del día")
        await processing_msg.edit_text("⚠️ Hubo un error analizando los picks de hoy. Probá de nuevo.")
        return

    if not picks:
        await processing_msg.edit_text(
            "🔍 No encontré picks con edge claro (+8%) hoy comparando historial vs cuotas. "
            "El mercado está bien ajustado, o todavía no hay props cargadas."
        )
        return

    lines = ["⭐ *Picks del día*\n"]
    total_len = len(lines[0])
    shown = 0
    for pick in picks:
        stars = confidence_stars(pick.edge_pct)
        block = (
            f"*{escape_md(pick.player)}*\n"
            f"{pick.market}: {pick.line} @ {pick.odds}\n"
            f"Partido: {pick.match}\n"
            f"Confianza: {stars}\n"
            f"📊 Nuestra probabilidad: {pick.our_probability_pct}% "
            f"(últimos {pick.sample_size} partidos) vs {pick.market_probability_pct}% del mercado\n"
            f"✅ Edge: +{pick.edge_pct}%\n"
        )
        if total_len + len(block) > 3800:
            break
        lines.append(block)
        total_len += len(block)
        shown += 1

    if shown < len(picks):
        lines.append(f"_(+{len(picks) - shown} más, no mostrados por espacio)_")

    lines.append(
        "\n_Nota: la probabilidad es empírica (frecuencia en partidos recientes), "
        "no una certeza. Cruzalo con tu propio criterio._"
    )

    await processing_msg.edit_text("\n".join(lines), parse_mode="Markdown")
