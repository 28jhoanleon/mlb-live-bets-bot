"""/calibracion — ¿los porcentajes que estima el bot son honestos?

Compara lo que el bot predijo ANTES de cada partido contra lo que
realmente pasó. Si dice 70% y en ese tramo acierta el 55%, está
inflado y conviene desconfiar de las soñadoras que arma.

Se alimenta de TODAS las legs resueltas, acertadas y falladas. Mirar
solo las ganadoras no diría nada: siempre daría 100%.
"""
from __future__ import annotations

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from app.db.database import calibracion, resumen_calibracion
from app.utils.logger import get_logger
from app.utils.telegram_helpers import escape_md

log = get_logger(__name__)

# Debajo de esto los porcentajes son ruido: con 8 legs, "acertó 5" no
# distingue un modelo de 60% de uno de 70%.
_MUESTRA_MINIMA = 20


async def calibracion_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    resumen = resumen_calibracion(chat_id)

    if resumen["total"] == 0:
        await update.message.reply_text(
            "Todavía no tengo apuestas resueltas para medir.\n\n"
            "Se van registrando solas cuando termina un ticket: mandame "
            "capturas y volvé en unos días.",
        )
        return

    lineas = ["📏 *Calibración del modelo*", ""]
    lineas.append(
        f"Legs resueltas: *{resumen['total']}* · acertadas: *{resumen['acertadas']}*"
    )
    lineas.append(
        f"Predije en promedio *{resumen['prob_media']}%* · pasó el *{resumen['real_pct']}%*"
    )

    diferencia = resumen["prob_media"] - resumen["real_pct"]
    if resumen["total"] < _MUESTRA_MINIMA:
        lineas.append("")
        lineas.append(
            f"⚠️ Con {resumen['total']} legs esto todavía no significa nada. "
            f"Desde {_MUESTRA_MINIMA} empieza a ser leíble."
        )
    elif diferencia > 7:
        lineas.append("")
        lineas.append("🔴 El modelo está *inflado*: promete más de lo que cumple.")
    elif diferencia < -7:
        lineas.append("")
        lineas.append("🟢 El modelo es *conservador*: cumple más de lo que promete.")
    else:
        lineas.append("")
        lineas.append("🟢 El modelo está *bien calibrado*.")

    tramos = calibracion(chat_id)
    if tramos:
        lineas.append("")
        lineas.append("*Por tramo* (predicho → real, muestra)")
        for t in tramos:
            marca = "·"
            if t["muestra"] >= 5:
                marca = "🔴" if t["predicho_medio"] - t["real_pct"] > 10 else "🟢"
            lineas.append(
                f"{marca} {escape_md(t['tramo'])}: "
                f"{t['real_pct']}% real ({t['muestra']})"
            )

    await update.message.reply_text(
        "\n".join(lineas), parse_mode=ParseMode.MARKDOWN
    )
