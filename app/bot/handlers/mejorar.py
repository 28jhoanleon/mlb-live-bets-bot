"""/mejorar — audita tu apuesta y propone una versión mejorada.

Automatiza lo que se venía haciendo a mano: armar una combinada, mirar
los números del bot, y rehacerla sacando los tramos flojos.
"""
from __future__ import annotations

import asyncio

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from app.analysis.auditoria import (
    PROB_FLOJA,
    armar_mejorada,
    auditar_legs,
)
from app.analysis.daily_picks import find_daily_picks
from app.db.database import get_active_bet
from app.utils.logger import get_logger
from app.utils.market_labels import nombre_stake_texto
from app.utils.telegram_helpers import edit_then_send_rest, escape_md

log = get_logger(__name__)


def _fmt_leg(leg) -> str:
    """Una leg auditada, con su semáforo."""
    mercado = nombre_stake_texto(leg.market)
    if leg.probabilidad is None:
        motivo = leg.error or "sin datos"
        return (f"⚪ {escape_md(leg.player)} — _{escape_md(mercado)}_ "
                f"{escape_md(leg.line)}\n   _{escape_md(motivo)}_")

    emoji = "🟢" if leg.es_fuerte else ("🔴" if leg.es_floja else "🟡")
    txt = (f"{emoji} {escape_md(leg.player)} — _{escape_md(mercado)}_ "
           f"{escape_md(leg.line)}\n"
           f"   *{leg.probabilidad}%* · promedio {leg.promedio}")
    if leg.sugerencia:
        txt += f"\n   💡 {escape_md(leg.sugerencia)}"
    return txt


def _fmt_pick(pick) -> str:
    mercado = nombre_stake_texto(pick.market)
    return (f"🟢 {escape_md(pick.player)} — _{escape_md(mercado)}_ "
            f"{escape_md(pick.line)} @ {pick.odds}\n"
            f"   *{pick.our_probability_pct}%* · el mercado paga como "
            f"{pick.market_probability_pct}%")


async def mejorar_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    guardada = get_active_bet(chat_id)
    tickets = (guardada or {}).get("bets", [])

    if not tickets:
        await update.message.reply_text(
            "No tenés apuestas cargadas. Mandame una captura y después /mejorar."
        )
        return

    legs_raw = [leg for t in tickets for leg in t.get("legs", [])]
    aviso = await update.message.reply_text(
        f"Revisando {len(legs_raw)} tramos..."
    )

    # Techo duro: si algo se traba, el usuario recibe una respuesta igual
    # en vez de quedarse mirando "Revisando..." indefinidamente.
    try:
        auditoria = await asyncio.wait_for(
            asyncio.to_thread(auditar_legs, legs_raw), timeout=120,
        )
    except asyncio.TimeoutError:
        log.warning("auditar_legs pasó el techo de tiempo")
        await aviso.edit_text(
            "Tardó demasiado en responder la API de estadísticas. "
            "Probá de nuevo en un rato."
        )
        return
    except Exception:
        log.exception("Error auditando el ticket")
        await aviso.edit_text("No pude revisar los tramos. Probá de nuevo.")
        return

    partes = ["🔍 *Tu apuesta, tramo por tramo*", ""]
    partes.extend(_fmt_leg(l) for l in auditoria.legs)

    if auditoria.probabilidad_combinada is not None:
        partes.append("")
        partes.append(
            f"*Que entren todas: {auditoria.probabilidad_combinada}%*"
        )

    # Diagnóstico
    partes.append("")
    if auditoria.flojas:
        nombres = ", ".join(escape_md(l.player) for l in auditoria.flojas)
        partes.append(
            f"🔴 *Te la están hundiendo:* {nombres} "
            f"(abajo del {PROB_FLOJA:g}%)"
        )
    if auditoria.fuertes:
        nombres = ", ".join(escape_md(l.player) for l in auditoria.fuertes)
        partes.append(f"🟢 *Lo que la sostiene:* {nombres}")
    if not auditoria.flojas:
        partes.append("🟢 No veo tramos flojos: está bien armada.")

    # Versión mejorada, solo si hay algo que mejorar
    if auditoria.flojas or auditoria.sin_datos:
        await aviso.edit_text(
            f"Revisé tus {len(legs_raw)} tramos. Buscando reemplazos..."
        )
        try:
            picks = await asyncio.wait_for(
                asyncio.to_thread(find_daily_picks), timeout=120,
            )
        except asyncio.TimeoutError:
            log.warning("find_daily_picks pasó el techo de tiempo")
            picks = []
        except Exception:
            log.exception("Error buscando picks para la mejorada")
            picks = []

        if picks:
            mejorada = armar_mejorada(auditoria, picks)
            cambios = [x for x in mejorada if not hasattr(x, "probabilidad")]
            if cambios:
                partes.append("")
                partes.append("✨ *Versión mejorada*")
                for item in mejorada:
                    if hasattr(item, "probabilidad"):
                        partes.append(_fmt_leg(item))
                    else:
                        partes.append(_fmt_pick(item))
                partes.append("")
                partes.append(
                    f"_Reemplacé {len(cambios)} tramo(s). Las cuotas son de "
                    "referencia: fijate en Stake antes de cargarla._"
                )
            else:
                partes.append("")
                partes.append(
                    "_No encontré reemplazos claramente mejores en los "
                    "partidos de hoy._"
                )
        else:
            partes.append("")
            partes.append(
                "_No pude traer los picks del día para proponer reemplazos "
                "(cuotas no disponibles)._"
            )

    await edit_then_send_rest(aviso, update, "\n".join(partes),
                              parse_mode=ParseMode.MARKDOWN)
