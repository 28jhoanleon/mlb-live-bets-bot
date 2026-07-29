"""Handlers de /games y /today."""

from telegram import Update
from telegram.ext import ContextTypes

from app.mlb.http import MLBClientError
from app.mlb.schedule import get_schedule
from app.utils.tiempo import formato_hora_fecha
from app.utils.logger import get_logger

log = get_logger(__name__)


def _format_time(iso_utc: str | None) -> str:
    """Hora local del usuario (Argentina por defecto), no UTC."""
    return formato_hora_fecha(iso_utc)


async def games(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Lista simple del calendario del día (sin pitchers ni estadio)."""
    try:
        schedule = get_schedule()
    except MLBClientError:
        await update.message.reply_text(
            "⚠️ No pude obtener el calendario ahora mismo. Probá en un rato."
        )
        return

    if not schedule:
        await update.message.reply_text("No hay partidos de MLB programados hoy.")
        return

    lines = ["⚾ *Partidos de hoy:*\n"]
    for g in schedule:
        lines.append(f"{g['away_team']} @ {g['home_team']} — {_format_time(g['game_time_utc'])}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def today(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Versión completa: partidos + pitchers probables + hora + estadio."""
    try:
        schedule = get_schedule()
    except MLBClientError:
        await update.message.reply_text(
            "⚠️ No pude obtener el calendario ahora mismo. Probá en un rato."
        )
        return

    if not schedule:
        await update.message.reply_text("No hay partidos de MLB programados hoy.")
        return

    blocks = []
    for g in schedule:
        away_p = g["away_pitcher"] or "TBD"
        home_p = g["home_pitcher"] or "TBD"
        blocks.append(
            f"⚾ *{g['away_team']} @ {g['home_team']}*\n"
            f"🕐 {_format_time(g['game_time_utc'])}\n"
            f"🏟️ {g['venue']}\n"
            f"🥎 Pitchers: {away_p} vs {home_p}\n"
            f"📋 Estado: {g['status']}"
        )

    await update.message.reply_text("\n\n".join(blocks), parse_mode="Markdown")
