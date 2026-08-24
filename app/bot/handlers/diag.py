"""/diag — por qué una leg no encuentra su partido.

Existe porque estuvimos varias rondas adivinando dónde se cortaba la
cadena (jugador → equipo → partido → datos en vivo). Este comando
recorre esos pasos e informa el resultado de cada uno, así el próximo
diagnóstico es una lectura y no una hipótesis.
"""
from __future__ import annotations

import asyncio

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from app.utils.logger import get_logger
from app.utils.telegram_helpers import escape_md

log = get_logger(__name__)


def _revisar(nombre: str) -> list[str]:
    lineas: list[str] = []

    # Paso 1: identificar al jugador
    from app.mlb.players import search_player

    try:
        jugador = search_player(nombre)
    except Exception as exc:
        return [f"🔴 *1. Buscar jugador*: falló — {escape_md(str(exc)[:120])}"]

    if not jugador:
        return [f"🔴 *1. Buscar jugador*: no encontré a {escape_md(nombre)}"]

    lineas.append(f"🟢 *1. Jugador*: {escape_md(jugador.get('full_name') or '?')}")

    # Paso 2: su equipo
    equipo = jugador.get("team")
    if not equipo:
        lineas.append("🔴 *2. Equipo*: la API no devolvió el equipo")
        lineas.append("   _Sin equipo no se puede deducir el partido._")
        return lineas
    lineas.append(f"🟢 *2. Equipo*: {escape_md(equipo)}")

    # Paso 3: el calendario de hoy
    from app.mlb.schedule import get_schedule_cacheado
    from app.utils.tiempo import hoy_local

    try:
        juegos = get_schedule_cacheado()
    except Exception as exc:
        lineas.append(f"🔴 *3. Calendario*: falló — {escape_md(str(exc)[:120])}")
        return lineas

    lineas.append(f"🟢 *3. Calendario* ({hoy_local()}): {len(juegos)} partidos")
    if not juegos:
        lineas.append("   _Sin partidos no hay nada contra qué cruzar._")
        return lineas

    # Paso 4: deducir el partido
    from app.web.service import _partido_del_jugador

    partido = _partido_del_jugador(nombre)
    if not partido:
        lineas.append("🔴 *4. Partido*: no lo encontré en el calendario")
        muestra = ", ".join(
            f"{j.get('away_team')} @ {j.get('home_team')}" for j in juegos[:3]
        )
        lineas.append(f"   _Hoy juegan, por ejemplo:_ {escape_md(muestra)}")
        return lineas

    lineas.append(f"🟢 *4. Partido*: {escape_md(partido)}")

    # Paso 5: datos en vivo
    from app.analysis.live_tracking import get_live_tracking_for_match

    try:
        datos = get_live_tracking_for_match(partido)
    except Exception as exc:
        lineas.append(f"🔴 *5. En vivo*: falló — {escape_md(str(exc)[:120])}")
        return lineas

    if not datos:
        lineas.append("🟡 *5. En vivo*: sin datos (¿todavía no empezó?)")
    else:
        boxscore, estado = datos
        lineas.append(
            f"🟢 *5. En vivo*: {escape_md(str(estado.get('status')))} · "
            f"{len(boxscore)} jugadores en el boxscore"
        )
        if jugador.get("full_name") in boxscore:
            lineas.append("🟢 *6. En el boxscore*: sí")
        else:
            lineas.append("🔴 *6. En el boxscore*: no aparece")

    return lineas


async def diag_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text(
            "Decime un jugador de tu apuesta. Ej: `/diag Yandy Diaz`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    nombre = " ".join(context.args)
    aviso = await update.message.reply_text(f"Revisando {nombre}...")

    try:
        lineas = await asyncio.to_thread(_revisar, nombre)
    except Exception:
        log.exception("Error en el diagnóstico")
        await aviso.edit_text("El diagnóstico mismo falló. Está en los logs.")
        return

    await aviso.edit_text(
        "🔎 *Diagnóstico*\n\n" + "\n".join(lineas), parse_mode=ParseMode.MARKDOWN
    )
