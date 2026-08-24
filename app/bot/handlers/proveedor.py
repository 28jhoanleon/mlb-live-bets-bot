"""/proveedor — de dónde salen las cuotas y cuánto queda.

Sirve para confirmar que una clave nueva quedó bien cargada sin tener
que esperar a que falle un barrido.
"""
from __future__ import annotations

import asyncio

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from app.odds import parlay
from app.utils.logger import get_logger

log = get_logger(__name__)


async def proveedor_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    aviso = await update.message.reply_text("Probando los proveedores de cuotas...")
    lineas = ["*Proveedores de cuotas*", ""]

    # --- ParlayAPI ---
    if not parlay.hay_clave():
        lineas.append("⚪ *ParlayAPI*: sin clave cargada")
    else:
        try:
            eventos = await asyncio.to_thread(parlay.get_events)
            restante = parlay.cuota_restante()
            lineas.append(f"🟢 *ParlayAPI*: anda · {len(eventos)} partidos")
            if restante is not None:
                lineas.append(f"   créditos restantes: *{restante}*")
                if restante < 50:
                    lineas.append("   ⚠️ *Se están por agotar.*")
        except parlay.ParlayClientError as e:
            lineas.append(f"🔴 *ParlayAPI*: {e}")
        except Exception:
            log.exception("Error probando ParlayAPI")
            lineas.append("🔴 *ParlayAPI*: error inesperado")

    # --- The Odds API (respaldo) ---
    from app.odds import theodds

    try:
        eventos = await asyncio.to_thread(theodds.get_events)
        restante = theodds.cuota_restante()
        lineas.append(f"🟢 *The Odds API* (respaldo): anda · {len(eventos)} partidos")
        if restante is not None:
            lineas.append(f"   consultas restantes: *{restante}*")
    except theodds.OddsClientError as e:
        lineas.append(f"🔴 *The Odds API*: {e}")
    except Exception:
        log.exception("Error probando The Odds API")
        lineas.append("🔴 *The Odds API*: error inesperado")

    lineas.append("")
    lineas.append("_Se usa ParlayAPI primero; si falla, cae al respaldo._")

    await aviso.edit_text("\n".join(lineas), parse_mode=ParseMode.MARKDOWN)
