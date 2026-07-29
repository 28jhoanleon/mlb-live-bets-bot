"""Handler de /live: partidos en curso con inning, outs, score y corredores."""
from telegram import Update
from telegram.ext import ContextTypes

from app.mlb.http import MLBClientError
from app.mlb.live import get_live_games_today
from app.utils.logger import get_logger

log = get_logger(__name__)


def _bases_diagram(bases: dict[str, bool]) -> str:
    # Diagrama simple en texto: 2B arriba, 1B y 3B abajo
    second = "🟢" if bases.get("second") else "⚪"
    first = "🟢" if bases.get("first") else "⚪"
    third = "🟢" if bases.get("third") else "⚪"
    return f"    {second}\n  {third}   {first}"


async def live(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        live_games = get_live_games_today()
    except MLBClientError:
        await update.message.reply_text(
            "⚠️ No pude obtener partidos en vivo ahora mismo. Probá en un rato."
        )
        return

    if not live_games:
        await update.message.reply_text("🔴 No hay partidos de MLB en vivo en este momento.")
        return

    blocks = []
    for g in live_games:
        inning_state = g.get("inning_state", "")
        inning = g.get("inning", "?")
        blocks.append(
            f"🔴 *{g['away_team']} {g.get('away_score', 0)} - "
            f"{g.get('home_score', 0)} {g['home_team']}*\n"
            f"⚾ {inning_state} {inning} | Outs: {g.get('outs', 0)}\n"
            f"{_bases_diagram(g.get('bases', {}))}"
        )

    await update.message.reply_text("\n\n".join(blocks), parse_mode="Markdown")
