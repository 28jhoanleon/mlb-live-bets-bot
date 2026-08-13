"""Construcción de la Application de python-telegram-bot y registro
de todos los handlers. main.py solo llama a build_app().run_polling()."""
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from app.bot.handlers import (
    analyze,
    borrar,
    calibracion,
    combos_historial,
    compare,
    games,
    history,
    limpiar,
    live,
    mejorar,
    miid,
    proveedor,
    props,
    screenshot,
    sonadora,
    start,
    value,
)
from app.config import settings
from app.db.database import init_db, prune_tickets_terminados
from app.jobs.registrar_resueltas import registrar_resueltas_job
from app.utils.logger import get_logger

log = get_logger(__name__)

# Cada cuánto se recalculan las apuestas guardadas para registrar las
# legs ya resueltas (lo que alimenta /calibracion). No hace falta que
# sea frecuente: los partidos duran horas.
_REGISTRO_INTERVAL_SECONDS = 900  # cada 15 minutos


async def _manejar_error(update, context) -> None:
    """Manejador global. El log decía "No error handlers are registered":
    cuando un handler crasheaba, la excepción se perdía y el mensaje de
    "Analizando..." quedaba congelado para siempre. Al menos ahora el
    usuario se entera de que algo falló."""
    log.exception("Excepción no atrapada en un handler", exc_info=context.error)
    try:
        if update and getattr(update, "effective_message", None):
            await update.effective_message.reply_text(
                "⚠️ Algo falló procesando ese comando. Ya quedó registrado."
            )
    except Exception:
        log.exception("Tampoco pude avisarle al usuario")


def build_app() -> Application:
    settings.validate()
    init_db()
    # Limpieza de arranque: la tabla de tickets terminados crece sola con
    # cada apuesta que se resuelve, y nadie la vaciaba nunca.
    try:
        prune_tickets_terminados()
    except Exception:
        log.warning("No pude limpiar registros viejos", exc_info=True)
    app = Application.builder().token(settings.bot_token).build()

    app.add_handler(CommandHandler("start", start.start))
    app.add_handler(CommandHandler("miid", miid.miid))
    app.add_handler(CommandHandler("help", start.help_command))
    app.add_handler(CommandHandler("games", games.games))
    app.add_handler(CommandHandler("today", games.today))
    app.add_handler(CommandHandler("live", live.live))
    app.add_handler(CommandHandler("props", props.props))
    app.add_handler(CommandHandler("strikeouts", props.strikeouts))
    app.add_handler(CommandHandler("hits", props.hits))
    app.add_handler(CommandHandler("hr", props.home_runs))
    app.add_handler(CommandHandler("analyze", analyze.analyze))
    app.add_handler(CommandHandler("compare", compare.compare))
    app.add_handler(CommandHandler("value", value.value))
    app.add_handler(CommandHandler("sonadora", sonadora.sonadora))
    app.add_handler(CommandHandler("sonadoras", sonadora.sonadora))
    app.add_handler(CommandHandler("combos", combos_historial.combos))
    app.add_handler(CommandHandler("refresh", screenshot.refresh_last_bet))
    app.add_handler(CommandHandler("nueva", screenshot.nueva_apuesta))
    app.add_handler(CommandHandler("mejorar", mejorar.mejorar_cmd))
    app.add_handler(CommandHandler("borrar", borrar.borrar_cmd))
    app.add_handler(CommandHandler("limpiar", limpiar.limpiar_cmd))
    app.add_handler(CommandHandler("proveedor", proveedor.proveedor_cmd))
    app.add_handler(CommandHandler("calibracion", calibracion.calibracion_cmd))
    app.add_handler(CommandHandler("historial", history.historial))
    app.add_handler(MessageHandler(filters.PHOTO, screenshot.handle_bet_screenshot))

    if app.job_queue is not None:
        app.job_queue.run_repeating(
            registrar_resueltas_job, interval=_REGISTRO_INTERVAL_SECONDS, first=60
        )
        log.info("Job de registro para calibración programado cada %ss", _REGISTRO_INTERVAL_SECONDS)
    else:
        log.warning(
            "job_queue no disponible (falta 'apscheduler') — las legs resueltas "
            "no se van a registrar solas y /calibracion se va a quedar vacío."
        )

    comandos = sorted({
        c
        for h in app.handlers.get(0, [])
        if isinstance(h, CommandHandler)
        for c in h.commands
    })
    extras = [
        tipo
        for tipo, presente in (("photo", any(
            isinstance(h, MessageHandler) for h in app.handlers.get(0, [])
        )),)
        if presente
    ]
    app.add_error_handler(_manejar_error)

    log.info("Handlers registrados: %s", ", ".join(comandos + extras))
    return app


def run() -> None:
    app = build_app()
    log.info("MLB Live Bets AI iniciado — polling...")
    app.run_polling()
