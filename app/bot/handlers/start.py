"""Handlers de /start y /help."""
from telegram import Update
from telegram.ext import ContextTypes

WELCOME = (
    "⚾ *MLB Live Bets AI*\n\n"
    "Tu analista de apuestas MLB. No solo te muestro partidos, "
    "te digo *dónde hay valor*.\n\n"
    "📅 /today — Partidos de hoy y pitchers probables\n"
    "🔴 /live — Partidos en vivo\n"
    "⭐ /analyze — Picks del día (probabilidad real vs cuota)\n"
    "🎯 /strikeouts · ⚾ /hits · 💥 /hr — Props filtradas por categoría\n"
    "📊 /props — Todas las props disponibles\n"
    "💰 /value — Combinadas con valor esperado (+EV)\n"
    "🌙 /sonadora — Combinadas largas de cuota alta\n"
    "📜 /combos — Si las combinadas sugeridas se dieron o no\n"
    "🎲 /sonadoras — Combinadas de cuota alta (baja probabilidad)\n"
    "⚔️ /compare — Comparar dos apuestas puntuales\n"
    "📜 /historial — Tus últimas apuestas analizadas\n"
    "🔔 /alertas — Avisos automáticos de +EV (🔕 /noalertas para apagarlos)\n\n"
    "📸 Enviame una *captura de tu apuesta* (Bet365, Betano, Stake, "
    "DraftKings, FanDuel) y te digo qué selecciones tiene, con probabilidad real "
    "o tracking en vivo si el partido ya empezó.\n"
    "🔄 /refresh — Actualiza el estado en vivo de tu última captura, sin volver a mandarla\n\n"
    "_Combinada larga que no entra en una foto: mandá varias juntas como álbum "
    "y las analizo como una sola apuesta. Si las mandás de a una, poné *+* en el "
    "pie de la foto para sumarla a la anterior._"
)

HELP = (
    "*Comandos disponibles:*\n\n"
    "/start — Bienvenida\n"
    "/help — Esta ayuda\n"
    "/games — Calendario del día\n"
    "/today — Partidos + pitchers probables + hora + estadio\n"
    "/live — Partidos en vivo (inning, outs, score, corredores)\n"
    "/analyze — Mejores picks del día (nuestra probabilidad vs cuota de mercado)\n"
    "/strikeouts — Props de ponches\n"
    "/hits — Props de hits\n"
    "/hr — Props de Home Runs\n"
    "/props — Todas las props disponibles\n"
    "/value — Combinadas +EV (solo con legs que ya tienen valor)\n"
    "/sonadora — Combinadas largas de cuota alta (probabilidad baja)\n"
    "/combos — Historial de combinadas sugeridas y si se dieron\n"
    "/sonadoras — Combinadas de 10x o más, la de mejor probabilidad disponible\n"
    "/compare Jugador, Mercado, Línea, Cuota vs Jugador2, ... — Comparar dos apuestas\n"
    "/historial — Tus últimas apuestas analizadas\n"
    "/alertas — Activar avisos automáticos de +EV\n"
    "/noalertas — Desactivar avisos automáticos\n"
    "/refresh — Actualiza el estado en vivo de tu última captura\n\n"
    "🏷️ *Varias apuestas a la vez*: escribí una etiqueta en el pie de la foto\n"
    "  (ej. *1*, *2*) y las capturas con la misma etiqueta se agrupan en\n"
    "  la misma apuesta, aunque crucen varios partidos.\n\n"
    "📸 *Combinadas largas* (no entran en una foto):\n"
    "  • Mandá varias fotos juntas como álbum, o\n"
    "  • Mandalas de a una con *+* en el pie de foto\n"
    "  Se juntan en una sola apuesta y /refresh las actualiza todas.\n\n"
    "📸 Enviá una captura de tu casa de apuestas para análisis automático "
    "(simple o combinada, con probabilidad histórica o tracking en vivo)."
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(WELCOME, parse_mode="Markdown")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP, parse_mode="Markdown")
