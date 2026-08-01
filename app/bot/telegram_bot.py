"""Construcción de la Application de python-telegram-bot y registro
de todos los handlers. main.py solo llama a build_app().run_polling()."""
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from app.bot.handlers import (
    alerts,
    analyze,
    calibracion,
    combos_historial,
    compare,
    games,
    history,
    limpiar,
    live,
    miid,
    props,
    screenshot,
    sonadora,
    start,
    statcast,
    value,
)
from app.config import settings
from app.db.database import init_db
from app.jobs.value_alerts import check_value_alerts_job
from app.utils.logger import get_logger

log = get_logger(__name__)

_ALERT_CHECK_INTERVAL_SECONDS = 300  # cada 5 minutos


def build_app() -> Application:
    settings.validate()
    init_db()
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
    app.add_handler(CommandHandler("limpiar", limpiar.limpiar_cmd))
    app.add_handler(CommandHandler("calibracion", calibracion.calibracion_cmd))
    app.add_handler(CommandHandler("statcast", statcast.statcast_cmd))
    app.add_handler(CommandHandler("historial", history.historial))
    app.add_handler(CommandHandler("alertas", alerts.alertas_on))
    app.add_handler(CommandHandler("noalertas", alerts.alertas_off))
    app.add_handler(MessageHandler(filters.PHOTO, screenshot.handle_bet_screenshot))

    if app.job_queue is not None:
        app.job_queue.run_repeating(
            check_value_alerts_job, interval=_ALERT_CHECK_INTERVAL_SECONDS, first=15
        )
        log.info("Job de alertas automáticas programado cada %ss", _ALERT_CHECK_INTERVAL_SECONDS)
    else:
        log.warning(
            "job_queue no disponible (falta 'apscheduler') — las alertas automáticas de /alertas "
            "no van a funcionar hasta instalar la dependencia. Ver requirements.txt."
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
    log.info("Handlers registrados: %s", ", ".join(comandos + extras))
    return app


def run() -> None:
    app = build_app()
    log.info("MLB Live Bets AI iniciado — polling...")
    app.run_polling()
