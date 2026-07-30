"""Job periódico: escanea value bets y les avisa a los chats
suscriptos, sin que nadie tenga que pedir /value manualmente.

Usa seen_value_alerts para no mandar la misma alerta dos veces (si el
job corre cada 5 minutos y la misma value bet sigue ahí, no lo vuelve
a spamear hasta que la cuota cambie o desaparezca y reaparezca).
"""
from __future__ import annotations

from telegram.ext import ContextTypes

from app.analysis.value import scan_value_bets
from app.utils.market_labels import format_value_bet_key
from app.db.database import (
    get_subscribed_chats,
    has_seen_alert,
    mark_alert_seen,
    prune_old_alerts,
)
from app.utils.logger import get_logger

log = get_logger(__name__)

_MIN_EDGE_FOR_ALERT = 5.0  # más exigente que el /value manual (3%), para no saturar de alertas chicas


def _alert_key(event: dict, outcome_key: str, bet) -> str:
    """Clave de dedup: mismo evento + mismo pick + misma casa + misma
    cuota redondeada. Si la cuota cambia, se considera una alerta nueva."""
    return f"{event.get('id', event.get('away_team'))}|{outcome_key}|{bet.side}|{bet.book}|{round(bet.price, 2)}"


async def check_value_alerts_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    chats = get_subscribed_chats()
    if not chats:
        return  # nadie suscripto, no hace falta ni escanear

    try:
        value_bets = scan_value_bets(min_edge_pct=_MIN_EDGE_FOR_ALERT, max_events=5)
    except Exception:
        log.exception("Error en el job de alertas de valor")
        return

    for event, key, bet in value_bets:
        alert_key = _alert_key(event, key, bet)
        if has_seen_alert(alert_key):
            continue
        mark_alert_seen(alert_key)

        text = (
            f"🚨 *Value Bet detectada*\n\n"
            f"*{event.get('away_team')} @ {event.get('home_team')}*\n"
            f"{format_value_bet_key(key, bet.side)}\n"
            f"💰 {bet.book} @ {bet.price}\n"
            f"📈 Prob. estimada: {bet.fair_probability}% | Implícita: {bet.implied_probability}%\n"
            f"✅ Valor: +{bet.edge_pct}%"
        )
        for chat_id in chats:
            try:
                await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")
            except Exception:
                log.exception("No pude mandar alerta a chat_id=%s", chat_id)

    prune_old_alerts(older_than_hours=12)
