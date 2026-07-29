"""Handler de fotos: recibe una captura de apuesta, la lee con OpenAI
Vision, y le suma:
  - Si el partido está EN VIVO: progreso real de esta noche (boxscore
    actual vs la línea), barra visual, probabilidad hacia adelante, y
    si el jugador sigue activo.
  - Si no, o si no encuentra el partido en vivo: probabilidad histórica
    basada en los últimos partidos del jugador.
Más el veredicto de la combinada si aplica.

Guarda el último análisis en SQLite (app.db.database) para que /refresh
pueda recalcular sin pedir la foto de nuevo — y para que sobreviva
reinicios del bot, a diferencia de la versión anterior en memoria.
"""
import asyncio

from telegram import Update
from telegram.ext import ContextTypes

from app.ai.vision import VisionAnalysisError, analyze_bet_screenshot
from app.analysis.live_tracking import LiveLegStatus, get_live_tracking_for_match, track_leg_live
from app.analysis.parlay import analyze_parlay
from app.analysis.probability import LegEstimate, ProbabilityError, estimate_leg_probability
from app.analysis.tickets import merge_tickets, normalize, to_storage
from app.bot.media_group import (
    agregar_imagen,
    cancelar_espera,
    esperar_resto_del_album,
    merge_analyses,
    recuperar_y_limpiar,
    registrar_espera,
)
from app.db.database import (
    clear_active_bet,
    get_active_bet,
    log_bet_analysis,
    save_active_bet,
)
from app.utils.logger import get_logger
from app.utils.progress_bar import build_form_bar
from app.utils.telegram_helpers import edit_then_send_rest, escape_md

log = get_logger(__name__)

# Mensaje de "analizando" por álbum, para no repetirlo por cada foto
_albumes_avisados: dict = {}


_DIVIDER = "━━━━━━━━━━━━━━━━"


def _clean_odds(leg: dict) -> str:
    """En combinadas SGM la casa muestra solo la cuota total, no la de
    cada leg. En ese caso no mostramos un '@' colgado."""
    odds = leg.get("odds")
    if odds and str(odds).strip().lower() not in ("none", "null", "-", "?"):
        return f" · {escape_md(odds)}"
    return ""


def _leg_title(index: int, leg: dict, emoji: str, is_parlay: bool) -> str:
    """Primera línea de la leg: número, estado de un vistazo y jugador.

    El nombre del partido NO va acá: en una combinada del mismo partido
    se repetiría en cada leg y es justo lo que hacía el mensaje ilegible.
    Va una sola vez, arriba de todo.
    """
    player = escape_md(leg.get("player") or "Sin jugador identificado")
    numero = f"*{index}* " if is_parlay else ""
    return f"{numero}{emoji} *{player}*"


def _leg_market_line(leg: dict) -> str:
    mercado = escape_md(leg.get("market", "?"))
    linea = escape_md(leg.get("line", "?"))
    return f"   {mercado} · {linea}{_clean_odds(leg)}"


def _format_live_leg(index: int, leg: dict, status: LiveLegStatus, is_parlay: bool) -> str:
    jugador_afuera = "🔴" in status.active_status
    emoji = "✅" if status.already_hit else ("🔴" if jugador_afuera else "⏳")

    partes = [
        _leg_title(index, leg, emoji, is_parlay),
        _leg_market_line(leg),
        # Monospace para que las barras queden alineadas entre legs.
        f"   `{status.progress_bar}`",
    ]

    # Leg ya cumplida: no hace falta probabilidad (ya pasó) ni si el
    # jugador salió (ya no cambia nada), pero SÍ decimos por qué no hay
    # más análisis. Antes desaparecía todo y parecía que el bot había
    # dejado de analizar.
    if status.already_hit:
        partes.append(f"   ✅ {escape_md(status.status_text)}")
        return "\n".join(partes)

    if jugador_afuera:
        # Antes se mostraban dos líneas rojas diciendo casi lo mismo.
        partes.append("   🔴 Salió del partido — improbable que se cumpla")
    else:
        partes.append(f"   {escape_md(status.status_text)}")
        partes.append(f"   {escape_md(status.active_status)}")

    return "\n".join(partes)


def _format_historical_leg(
    index: int, leg: dict, estimate: LegEstimate | None, error: str | None, is_parlay: bool
) -> str:
    if estimate:
        emoji = "🟢" if estimate.probability_pct >= 60 else ("🟡" if estimate.probability_pct >= 35 else "🔴")
    else:
        emoji = "⚠️"

    partes = [_leg_title(index, leg, emoji, is_parlay), _leg_market_line(leg)]

    if estimate:
        # Barra de forma reciente: cuántos de sus últimos partidos superó
        # la línea. Mide algo distinto a la barra en vivo (regularidad vs
        # avance de hoy), por eso el texto lo aclara. Está para que TODAS
        # las legs tengan referencia visual: antes solo la tenían las que
        # se podían seguir en vivo y la lista quedaba cortada al medio.
        cumplidos = round(estimate.probability_pct / 100 * estimate.sample_size)
        partes.append(f"   Forma  `{build_form_bar(cumplidos, estimate.sample_size)}`")
        partes.append(
            f"   *{estimate.probability_pct}%* en sus últimos "
            f"{estimate.sample_size} partidos · promedio {estimate.avg_value}"
        )
    elif error:
        partes.append(f"   {escape_md(error)}")

    return "\n".join(partes)


def _live_header(live_state: dict, is_parlay: bool) -> list[str]:
    """Encabezado con el partido, el marcador y la entrada — una sola
    vez, en vez de repetir el nombre del partido en cada leg."""
    away = escape_md(live_state.get("away_team") or "")
    home = escape_md(live_state.get("home_team") or "")
    away_score = live_state.get("away_score")
    home_score = live_state.get("home_score")
    inning = live_state.get("inning")
    estado = live_state.get("inning_state") or ""

    titulo = "🔴 *EN VIVO*"
    if inning:
        traducido = {"Top": "arriba", "Bottom": "abajo", "Middle": "medio", "End": "fin"}.get(estado, estado.lower())
        titulo += f" · {inning}ª entrada {traducido}".rstrip()

    lineas = [titulo]
    if away and home:
        # Convención MLB: visitante @ local. El '@' evita la ambigüedad
        # de "Equipo 2 — 7 Equipo", donde no se sabe quién juega de local
        # ni a qué equipo corresponde cada número.
        if away_score is not None and home_score is not None:
            lineas.append(f"{away} *{away_score}* @ {home} *{home_score}*")
        else:
            lineas.append(f"{away} @ {home}")
    return lineas


def _static_header(legs: list[dict], is_parlay: bool) -> list[str]:
    tipo = "🧩 *Combinada*" if is_parlay else "🎯 *Apuesta*"
    partido = escape_md(legs[0].get("match", "")) if legs else ""
    return [tipo, partido] if partido else [tipo]


async def _estimate_leg_historical(leg: dict) -> tuple[LegEstimate | None, str | None]:
    player = leg.get("player")
    if not player:
        return None, (
            "No pude leer el jugador de esta leg. Puede ser un mercado de equipo, "
            "o que el nombre quedara cortado en la captura."
        )
    try:
        estimate = estimate_leg_probability(player, leg.get("market", ""), leg.get("line", ""))
        return estimate, None
    except ProbabilityError as exc:
        return None, str(exc)[:150]
    except Exception:
        log.exception("Error inesperado estimando probabilidad de leg: %s", leg)
        return None, "No pude calcular probabilidad para esta leg."


async def _format_ticket(ticket: dict, indice: int, total_tickets: int) -> str:
    """Formatea UN ticket (una apuesta). Cada tarjeta de la casa de
    apuestas es un ticket independiente: se gana o se pierde por su
    cuenta, así que se muestra con su propio encabezado y su propio
    conteo de legs cumplidas."""
    legs = ticket.get("legs", [])
    if not legs:
        return ""

    is_parlay = len(legs) > 1

    live_data = None
    if ticket.get("is_live"):
        try:
            live_data = get_live_tracking_for_match(ticket.get("match", ""))
        except Exception:
            log.exception("Error buscando partido en vivo")

    estimates: list[LegEstimate] = []
    live_statuses: list[LiveLegStatus] = []
    leg_bloques: list[str] = []

    for i, leg in enumerate(legs, 1):
        if live_data:
            boxscore, live_state = live_data
            try:
                status = track_leg_live(leg, boxscore, live_state)
                leg_bloques.append(_format_live_leg(i, leg, status, is_parlay))
                live_statuses.append(status)
                continue
            except ProbabilityError:
                pass

        estimate, error = await _estimate_leg_historical(leg)
        leg_bloques.append(_format_historical_leg(i, leg, estimate, error, is_parlay))
        if estimate:
            estimates.append(estimate)

    # --- Encabezado del ticket ---
    titulo = f"🎫 *Apuesta {indice}/{total_tickets}*" if total_tickets > 1 else "🎫 *Apuesta*"
    cuota = ticket.get("total_odds")
    if cuota:
        titulo += f" · paga *{escape_md(str(cuota))}*"

    cabecera = [titulo]
    if live_data:
        _, live_state = live_data
        cabecera.extend(_live_header(live_state, is_parlay))
    else:
        partido = escape_md(ticket.get("match", ""))
        if partido:
            cabecera.append(partido)

    if live_data and len(live_statuses) == len(legs) and is_parlay:
        cumplidas = sum(1 for s in live_statuses if s.already_hit)
        cabecera.append(f"*{cumplidas} de {len(legs)} legs cumplidas*")

    bloques = ["\n".join(cabecera)]
    bloques.extend(leg_bloques)

    # --- Cierre del ticket ---
    if not live_data and is_parlay and len(estimates) == len(legs):
        verdict = analyze_parlay(estimates, same_game=True)
        bloques.append(
            f"*Probabilidad combinada: {verdict.combined_probability_pct}%*\n"
            f"{verdict.risk_label}\n"
            f"{escape_md(verdict.recommendation)}"
        )
    elif not live_data and is_parlay and len(estimates) < len(legs):
        bloques.append(
            "_No pude estimar todas las legs, así que no calculo la combinada._"
        )

    return "\n\n".join(bloques)


async def _format_full_analysis(analysis: dict) -> str:
    """Arma la respuesta completa: un bloque por cada apuesta detectada."""
    tickets = normalize(analysis)
    if not tickets:
        return "No pude identificar selecciones claras en la imagen. Probá con una captura más nítida."

    partes: list[str] = []
    if len(tickets) > 1:
        total_legs = sum(len(t.get("legs", [])) for t in tickets)
        partes.append(
            f"📋 *{len(tickets)} apuestas detectadas* · {total_legs} legs en total"
        )

    for i, ticket in enumerate(tickets, 1):
        bloque = await _format_ticket(ticket, i, len(tickets))
        if bloque:
            partes.append(_DIVIDER)
            partes.append(bloque)

    if any(t.get("is_live") for t in tickets):
        partes.append(_DIVIDER + "\n🔄 /refresh para actualizar sin mandar la foto")

    return "\n\n".join(partes)


async def _procesar_y_responder(
    imagenes: list[bytes], processing_msg, chat_id: int, acumular: bool = True
) -> None:
    """Analiza las capturas y responde.

    `acumular=True` (por defecto): los tickets nuevos se suman a los que
    ya estaban guardados. No hace falta que el usuario escriba nada — si
    la apuesta es de otro partido queda como un ticket aparte, y si es
    del mismo ticket se fusionan las legs sin duplicar. Para empezar de
    cero está /nueva.
    """
    analisis: list[dict] = []
    fallidas = 0

    for i, img in enumerate(imagenes, 1):
        if len(imagenes) > 1:
            try:
                await processing_msg.edit_text(
                    f"🔍 Analizando captura {i} de {len(imagenes)}..."
                )
            except Exception:
                pass  # el edit es cosmético, no debe cortar el análisis
        try:
            analisis.append(analyze_bet_screenshot(img))
        except VisionAnalysisError as exc:
            log.warning("Falló el análisis de una captura: %s", exc)
            fallidas += 1
        except Exception:
            log.exception("Error inesperado analizando una captura")
            fallidas += 1

    if not analisis:
        await processing_msg.edit_text(
            "⚠️ No pude leer ninguna de las capturas. Probá con imágenes más nítidas."
        )
        return

    tickets_nuevos = merge_tickets([normalize(a) for a in analisis])

    tickets_previos: list[dict] = []
    if acumular:
        anterior = get_active_bet(chat_id)
        if anterior:
            tickets_previos = normalize(anterior)

    tickets = merge_tickets([tickets_previos, tickets_nuevos]) if tickets_previos else tickets_nuevos
    analysis = to_storage(tickets)

    # Guardamos en SQLite (sobrevive reinicios) para que /refresh pueda
    # recalcular sin las fotos, y para el historial.
    save_active_bet(chat_id, analysis)
    try:
        log_bet_analysis(chat_id, analysis)
    except Exception:
        log.exception("No pude guardar el historial (no bloquea la respuesta)")

    try:
        result_text = await _format_full_analysis(analysis)
    except Exception:
        log.exception("Error inesperado calculando probabilidades")
        result_text = "⚠️ Detecté la apuesta pero hubo un error calculando probabilidades."

    # Confirmación de recepción: cuántas capturas entraron y cuántas
    # apuestas salieron de ellas.
    recibidas = len(imagenes)
    encabezado = f"📸 {recibidas} captura{'s' if recibidas != 1 else ''} recibida{'s' if recibidas != 1 else ''}"
    if tickets_previos:
        nuevas = len(tickets) - len(tickets_previos)
        if nuevas > 0:
            encabezado += f" · {nuevas} apuesta{'s' if nuevas != 1 else ''} nueva{'s' if nuevas != 1 else ''}"
        else:
            encabezado += " · sumadas a las apuestas guardadas"
    if fallidas:
        encabezado += f" · ⚠️ {fallidas} ilegible{'s' if fallidas != 1 else ''}"

    await edit_then_send_rest(processing_msg, f"_{encabezado}_\n\n{result_text}")


async def _procesar_album(media_group_id: str, processing_msg, chat_id: int) -> None:
    """Espera a que lleguen todas las fotos del álbum y las procesa juntas."""
    try:
        await esperar_resto_del_album()
    except asyncio.CancelledError:
        return  # llegó otra foto: el temporizador se reinició

    imagenes = recuperar_y_limpiar(media_group_id)
    if not imagenes:
        return

    await processing_msg.edit_text(f"🔍 Analizando {len(imagenes)} capturas...")
    await _procesar_y_responder(imagenes, processing_msg, chat_id)


async def handle_bet_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    photo = update.message.photo[-1]
    tg_file = await context.bot.get_file(photo.file_id)
    chat_id = update.effective_chat.id

    try:
        image_bytes = bytes(await tg_file.download_as_bytearray())
    except Exception:
        log.exception("No pude descargar la imagen")
        await update.message.reply_text("⚠️ No pude descargar la imagen. Probá de nuevo.")
        return

    media_group_id = update.message.media_group_id

    # Las capturas se acumulan solas: no hace falta escribir nada. Si la
    # apuesta es de otro partido queda como ticket aparte; si es del
    # mismo, se fusionan las legs sin duplicar. Para arrancar de cero
    # está /nueva.
    if not media_group_id:
        processing_msg = await update.message.reply_text("🔍 Analizando la captura...")
        await _procesar_y_responder([image_bytes], processing_msg, chat_id)
        return

    # Álbum: las fotos llegan en mensajes separados. Acumulamos y
    # reiniciamos el temporizador con cada una; procesamos cuando dejan
    # de llegar. Solo la PRIMERA foto crea el mensaje de "analizando"
    # para no llenar el chat de mensajes repetidos.
    es_primera = media_group_id not in _albumes_avisados
    cancelar_espera(media_group_id)
    grupo = agregar_imagen(media_group_id, image_bytes)
    recibidas = len(grupo.imagenes)

    if es_primera:
        _albumes_avisados[media_group_id] = await update.message.reply_text(
            "📥 Recibiendo capturas... (1)"
        )

    processing_msg = _albumes_avisados[media_group_id]

    # Confirmación visible de cuántas fotos llegaron. Telegram no avisa
    # cuántas faltan, así que mostramos el acumulado en vez de "1 de N".
    if not es_primera:
        try:
            await processing_msg.edit_text(f"📥 Recibiendo capturas... ({recibidas})")
        except Exception:
            pass  # editar de más no debe romper el flujo
    tarea = asyncio.create_task(_procesar_album(media_group_id, processing_msg, chat_id))
    registrar_espera(media_group_id, tarea)

    # Limpieza: cuando la tarea termina, el álbum ya no se sigue
    tarea.add_done_callback(lambda _: _albumes_avisados.pop(media_group_id, None))


async def refresh_last_bet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    analysis = get_active_bet(update.effective_chat.id)
    if not analysis:
        await update.message.reply_text(
            "No tengo ninguna apuesta guardada todavía. Mandame una captura primero."
        )
        return

    processing_msg = await update.message.reply_text("🔄 Actualizando...")

    try:
        result_text = await _format_full_analysis(analysis)
    except Exception:
        log.exception("Error inesperado actualizando análisis")
        await processing_msg.edit_text("⚠️ Hubo un error actualizando el análisis.")
        return

    await edit_then_send_rest(processing_msg, result_text)


async def nueva_apuesta(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Borra las apuestas guardadas para arrancar de cero.

    Necesario porque las capturas se acumulan por defecto: sin esto, las
    apuestas de ayer seguirían apareciendo en el análisis de hoy.
    """
    chat_id = update.effective_chat.id
    anteriores = normalize(get_active_bet(chat_id) or {})

    clear_active_bet(chat_id)

    if anteriores:
        await update.message.reply_text(
            f"🗑️ Listo, borré {len(anteriores)} apuesta"
            f"{'s' if len(anteriores) != 1 else ''} guardada"
            f"{'s' if len(anteriores) != 1 else ''}.\n\n"
            "Mandá las capturas nuevas cuando quieras."
        )
    else:
        await update.message.reply_text(
            "No tenías apuestas guardadas. Mandá una captura para empezar."
        )
