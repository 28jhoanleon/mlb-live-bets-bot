"""/statcast <jugador> — qué dice Statcast de un bateador.

Muestra xBA contra BA: si el esperado es más alto que el real, el
jugador viene bateando bien y el resultado no lo acompañó todavía.
"""
from __future__ import annotations

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from app.mlb.statcast import buscar_jugador, diferencia_xba
from app.utils.logger import get_logger
from app.utils.telegram_helpers import escape_md

log = get_logger(__name__)


async def statcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text(
            "Decime un jugador. Ej: `/statcast Aaron Judge`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    nombre = " ".join(context.args)
    await update.message.chat.send_action("typing")

    import asyncio

    datos = await asyncio.to_thread(buscar_jugador, nombre)
    if not datos:
        await update.message.reply_text(
            f"No encontré datos de Statcast para *{escape_md(nombre)}*.\n"
            "Puede que no llegue al mínimo de apariciones o que Savant "
            "no esté respondiendo.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    dif = diferencia_xba(datos)
    lineas = [f"📊 *{escape_md(datos['nombre'])}*", ""]
    lineas.append(f"Promedio real: *{datos['ba']:.3f}*" if datos.get("ba") is not None else "")
    lineas.append(f"Esperado (xBA): *{datos['xba']:.3f}*" if datos.get("xba") is not None else "")
    if datos.get("xwoba") is not None:
        lineas.append(f"xwOBA: *{datos['xwoba']:.3f}*")
    if datos.get("pa"):
        lineas.append(f"Apariciones: {int(datos['pa'])}")

    if dif is not None:
        lineas.append("")
        if dif >= 0.020:
            lineas.append(
                f"🟢 Está bateando *mejor* de lo que muestra su promedio "
                f"(+{dif:.3f}). El resultado no lo acompañó todavía."
            )
        elif dif <= -0.020:
            lineas.append(
                f"🔴 Viene con *suerte a favor* ({dif:.3f}): su promedio "
                f"está por encima de lo que genera."
            )
        else:
            lineas.append(f"⚪ Su promedio refleja lo que genera ({dif:+.3f}).")

    lineas.append("")
    lineas.append("_Datos de temporada, no de este partido._")

    await update.message.reply_text(
        "\n".join(l for l in lineas if l != ""), parse_mode=ParseMode.MARKDOWN
    )
