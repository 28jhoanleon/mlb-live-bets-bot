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
    OBJETIVO_SEGURO,
    PROB_FLOJA,
    armar_mejorada,
    auditar_legs,
    version_segura,
)
from app.analysis.daily_picks import find_daily_picks
from app.db.database import get_active_bet
from app.utils.logger import get_logger
from app.utils.equipos import partido_corto
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


def _fmt_tramo_seguro(t) -> str:
    mercado = nombre_stake_texto(t.market)
    if t.cambio:
        return (
            f"🟢 {escape_md(t.player)} — _{escape_md(mercado)}_\n"
            f"   {escape_md(t.linea_original)} → *{escape_md(t.linea_nueva)}* "
            f"· {t.probabilidad}%"
        )
    return (
        f"✅ {escape_md(t.player)} — _{escape_md(mercado)}_\n"
        f"   {escape_md(t.linea_nueva)} · {t.probabilidad}% _(ya estaba bien)_"
    )


async def _responder_version_segura(aviso, legs_raw: list[dict]) -> None:
    """Baja las líneas hasta que cada tramo sea muy probable.

    Es lo opuesto a una soñadora: se resigna cuota para que la
    combinada entre. Mismos jugadores y mercados, líneas más blandas.
    """
    try:
        tramos, combinada = await asyncio.wait_for(
            asyncio.to_thread(version_segura, legs_raw), timeout=120,
        )
    except asyncio.TimeoutError:
        await aviso.edit_text("Tardó demasiado. Probá de nuevo en un rato.")
        return
    except Exception:
        log.exception("Error armando la versión segura")
        await aviso.edit_text("No pude armar la versión segura.")
        return

    if not tramos:
        await aviso.edit_text(
            "No pude calcular líneas alternativas para estos tramos."
        )
        return

    partes = [f"🛡 *Versión segura* (objetivo {OBJETIVO_SEGURO:g}% por tramo)", ""]

    # Agrupado por partido: con 11 tramos de 5 juegos distintos, una
    # lista plana es ilegible.
    por_partido: dict[str, list] = {}
    for t in tramos:
        por_partido.setdefault(t.match or "Sin partido", []).append(t)

    for partido, del_partido in por_partido.items():
        if len(por_partido) > 1:
            partes.append(f"*{escape_md(partido_corto(partido))}*")
        for t in del_partido:
            partes.append(_fmt_tramo_seguro(t))
        if len(por_partido) > 1:
            partes.append("")


    if combinada is not None:
        partes.append("")
        partes.append(f"*Que entren todas: {combinada}%*")
        if combinada < 60:
            partes.append(
                "\n_Ojo: aunque cada tramo sea muy probable, multiplicarlos "
                "baja mucho el total. Menos tramos = más chance real._"
            )

    partes.append("")
    partes.append("_Paga bastante menos que la original: es el precio de la seguridad._")

    await edit_then_send_rest(aviso, "\n".join(partes), parse_mode=ParseMode.MARKDOWN)


async def mejorar_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    guardada = get_active_bet(chat_id)
    tickets = (guardada or {}).get("bets", [])

    if not tickets:
        await update.message.reply_text(
            "No tenés apuestas cargadas. Mandame una captura y después /mejorar."
        )
        return

    # Si hay varias apuestas, se elige cuál: antes se auditaban todas
    # juntas y el resultado mezclaba tramos de apuestas distintas.
    if len(tickets) > 1 and False:
        lineas = ["Tenés *varias apuestas*. ¿Cuál mejoro?", ""]
        for i, t in enumerate(tickets, 1):
            legs = t.get("legs", [])
            partido = legs[0].get("match", "?") if legs else "?"
            cuota = t.get("total_odds")
            extra = f" · paga {cuota}" if cuota else ""
            lineas.append(f"*{i}.* {escape_md(partido)} — {len(legs)} tramos{extra}")
        lineas.append("")
        lineas.append("Mandá `/mejorar 2` para elegir una.")
        lineas.append("O `/mejorar` a secas para verlas todas, agrupadas por partido.")
        await update.message.reply_text("\n".join(lineas), parse_mode=ParseMode.MARKDOWN)
        return

    elegido = tickets
    args = [a.lower() for a in (context.args or [])]
    # El modo seguro es el que se usa siempre: bajar líneas para que la
    # apuesta entre. "arriesgado" queda como opción explícita para el
    # comportamiento viejo (buscar reemplazos de mayor cuota).
    modo_seguro = "arriesgado" not in args
    numeros = [a for a in args if a.isdigit()]
    if numeros:
        idx = int(numeros[0])
        if idx < 1 or idx > len(tickets):
            await update.message.reply_text(f"No hay una apuesta número {idx}.")
            return
        elegido = [tickets[idx - 1]]

    tickets = elegido

    legs_raw = [leg for t in tickets for leg in t.get("legs", [])]
    aviso = await update.message.reply_text(
        f"Revisando {len(legs_raw)} tramos..."
    )

    if modo_seguro:
        await _responder_version_segura(aviso, legs_raw)
        return

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

    await edit_then_send_rest(aviso, "\n".join(partes),
                              parse_mode=ParseMode.MARKDOWN)
