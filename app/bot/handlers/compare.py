"""Handler de /compare: compara dos apuestas puntuales y dice cuál
tiene más valor, usando nuestra probabilidad empírica (últimos partidos
reales) contra la cuota que le pases.

Formato esperado (flexible, separado por " vs "):
/compare Jugador A, Mercado, Over 6.5, 1.90 vs Jugador B, Mercado, Over 5.5, 2.10

Ejemplo real:
/compare Woo, Strikeouts, Over 6.5, 1.90 vs Yamamoto, Strikeouts, Over 5.5, 2.05
"""
from telegram import Update
from telegram.ext import ContextTypes

from app.analysis.probability import LegEstimate, ProbabilityError, estimate_leg_probability
from app.analysis.value import implied_probability
from app.utils.logger import get_logger
from app.utils.telegram_helpers import escape_md

log = get_logger(__name__)

_USAGE = (
    "Uso: `/compare Jugador, Mercado, Over 6.5, 1.90 vs Jugador2, Mercado2, Over 5.5, 2.05`\n\n"
    "Ejemplo:\n`/compare Woo, Strikeouts, Over 6.5, 1.90 vs Yamamoto, Strikeouts, Over 5.5, 2.05`"
)


def _parse_side(text: str) -> tuple[str, str, str, float]:
    """'Woo, Strikeouts, Over 6.5, 1.90' -> (player, market, line, odds)."""
    parts = [p.strip() for p in text.split(",")]
    if len(parts) != 4:
        raise ValueError("Formato inválido")
    player, market, line, odds_text = parts
    return player, market, line, float(odds_text)


def _edge_for_side(player: str, market: str, line: str, odds: float) -> tuple[LegEstimate, float]:
    estimate = estimate_leg_probability(player, market, line)
    market_prob = implied_probability(odds) * 100
    edge = estimate.probability_pct - market_prob
    return estimate, round(edge, 1)


async def compare(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    raw_text = " ".join(context.args) if context.args else ""
    if " vs " not in raw_text:
        await update.message.reply_text(_USAGE, parse_mode="Markdown")
        return

    side_a_text, side_b_text = raw_text.split(" vs ", 1)

    try:
        player_a, market_a, line_a, odds_a = _parse_side(side_a_text)
        player_b, market_b, line_b, odds_b = _parse_side(side_b_text)
    except ValueError:
        await update.message.reply_text(
            "No pude interpretar el formato. " + _USAGE, parse_mode="Markdown"
        )
        return

    try:
        estimate_a, edge_a = _edge_for_side(player_a, market_a, line_a, odds_a)
    except ProbabilityError as exc:
        await update.message.reply_text(f"⚠️ Con {escape_md(player_a)}: {escape_md(str(exc)[:200])}")
        return

    try:
        estimate_b, edge_b = _edge_for_side(player_b, market_b, line_b, odds_b)
    except ProbabilityError as exc:
        await update.message.reply_text(f"⚠️ Con {escape_md(player_b)}: {escape_md(str(exc)[:200])}")
        return

    winner = estimate_a if edge_a >= edge_b else estimate_b
    winner_label = player_a if edge_a >= edge_b else player_b

    # El texto de /compare lo escribe el usuario, así que escapamos todo
    # lo dinámico: un '_' o '*' suelto rompería el mensaje entero.
    text = (
        f"⚔️ *Comparación*\n\n"
        f"*{escape_md(estimate_a.player)}* — {escape_md(market_a)}: "
        f"{escape_md(line_a)} @ {odds_a}\n"
        f"  📊 {estimate_a.probability_pct}% (últimos {estimate_a.sample_size} partidos) "
        f"vs {round(implied_probability(odds_a) * 100, 1)}% de la cuota\n"
        f"  Edge: {'+' if edge_a >= 0 else ''}{edge_a}%\n\n"
        f"*{escape_md(estimate_b.player)}* — {escape_md(market_b)}: "
        f"{escape_md(line_b)} @ {odds_b}\n"
        f"  📊 {estimate_b.probability_pct}% (últimos {estimate_b.sample_size} partidos) "
        f"vs {round(implied_probability(odds_b) * 100, 1)}% de la cuota\n"
        f"  Edge: {'+' if edge_b >= 0 else ''}{edge_b}%\n\n"
        f"✅ *Mayor valor: {escape_md(winner_label)}*"
    )

    await update.message.reply_text(text, parse_mode="Markdown")
