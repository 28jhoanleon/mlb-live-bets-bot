"""Handler de /props y sus filtros (/strikeouts, /hits, /hr): props
disponibles cruzando MLB Stats API (para saber qué partidos hay) con
The Odds API (para las líneas y cuotas)."""
from telegram import Update
from telegram.ext import ContextTypes

from app.odds.theodds import OddsClientError, get_events, get_player_props
from app.utils.logger import get_logger
from app.utils.telegram_helpers import escape_md

log = get_logger(__name__)

_MARKET_LABELS = {
    "pitcher_strikeouts": "🎯 Ponches",
    "batter_hits": "⚾ Hits",
    "batter_home_runs": "💥 Home Runs",
}

_TELEGRAM_MSG_LIMIT = 3800  # margen bajo el límite real de 4096
_MAX_EVENTS = 3  # limita cuántos partidos consultamos (cuota de API + tamaño de mensaje)
_MAX_OUTCOMES_PER_EVENT = 6  # limita líneas por partido para no saturar el mensaje
_ALL_MARKETS = "pitcher_strikeouts,batter_hits,batter_home_runs"


def _format_event_props(event: dict, props_data: dict) -> str:
    lines = [f"*{escape_md(event['away_team'])} @ {escape_md(event['home_team'])}*"]
    seen = 0
    for book in props_data.get("bookmakers", []):
        for market in book.get("markets", []):
            label = _MARKET_LABELS.get(market.get("key"), market.get("key"))
            for outcome in market.get("outcomes", []):
                if seen >= _MAX_OUTCOMES_PER_EVENT:
                    lines.append("  _(...más disponibles, usá /value para ver los mejores)_")
                    return "\n".join(lines)
                player = outcome.get("description", outcome.get("name", "?"))
                point = outcome.get("point")
                price = outcome.get("price")
                side = outcome.get("name", "")
                point_str = f" {point}" if point is not None else ""
                lines.append(
                    f"  {label} — {escape_md(player)}: {escape_md(side)}{point_str} "
                    f"@ {price} ({escape_md(book.get('title'))})"
                )
                seen += 1
    if seen == 0:
        return ""
    return "\n".join(lines)


def _chunk_blocks(blocks: list[str], header: str) -> list[str]:
    """Junta bloques en mensajes que no superen el límite de Telegram."""
    messages = []
    current = [header]
    current_len = len(header)
    for block in blocks:
        if current_len + len(block) + 2 > _TELEGRAM_MSG_LIMIT:
            messages.append("\n\n".join(current))
            current = [block]
            current_len = len(block)
        else:
            current.append(block)
            current_len += len(block) + 2
    if len(current) > (1 if current[0] == header else 0):
        messages.append("\n\n".join(current))
    return messages


async def _send_props(update: Update, markets: str, header: str, empty_msg: str) -> None:
    try:
        events = get_events()
    except OddsClientError as exc:
        await update.message.reply_text(f"⚠️ {str(exc)[:300]}")
        return

    if not events:
        await update.message.reply_text("No hay eventos de MLB disponibles ahora mismo.")
        return

    blocks = []
    for event in events[:_MAX_EVENTS]:
        try:
            props_data = get_player_props(event["id"], markets=markets)
        except OddsClientError:
            continue
        formatted = _format_event_props(
            {"away_team": event.get("away_team"), "home_team": event.get("home_team")},
            props_data,
        )
        if formatted:
            blocks.append(formatted)

    if not blocks:
        await update.message.reply_text(empty_msg)
        return

    for msg in _chunk_blocks(blocks, header):
        await update.message.reply_text(msg, parse_mode="Markdown")


async def props(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_props(
        update,
        _ALL_MARKETS,
        "📊 *Props disponibles:*",
        "No encontré props cargadas todavía para los partidos de hoy "
        "(suelen publicarse más cerca del first pitch).",
    )


async def strikeouts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_props(
        update,
        "pitcher_strikeouts",
        "🎯 *Picks de ponches:*",
        "No encontré props de ponches cargadas todavía para hoy.",
    )


async def hits(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_props(
        update,
        "batter_hits",
        "⚾ *Picks de hits:*",
        "No encontré props de hits cargadas todavía para hoy.",
    )


async def home_runs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_props(
        update,
        "batter_home_runs",
        "💥 *Picks de Home Runs:*",
        "No encontré props de Home Runs cargadas todavía para hoy.",
    )
