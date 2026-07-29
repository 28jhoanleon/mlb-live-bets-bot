"""Handlers de /alertas y /noalertas: suscripción a avisos automáticos
de value bets, sin tener que pedir /value a mano."""
from telegram import Update
from telegram.ext import ContextTypes

from app.db.database import subscribe_alerts, unsubscribe_alerts
from app.utils.logger import get_logger

log = get_logger(__name__)


async def alertas_on(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    subscribe_alerts(update.effective_chat.id)
    await update.message.reply_text(
        "🔔 Listo, te aviso automáticamente cuando aparezca una value bet (+5% de edge o más). "
        "Usá /noalertas para desactivarlo."
    )


async def alertas_off(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    unsubscribe_alerts(update.effective_chat.id)
    await update.message.reply_text("🔕 Listo, ya no te mando alertas automáticas.")
