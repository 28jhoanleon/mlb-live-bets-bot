"""Punto de entrada: levanta el bot de Telegram y el servidor web juntos.

Van en el MISMO proceso a propósito: un solo servicio en Railway, una
sola base de datos SQLite y una sola copia de la lógica de análisis. Si
fueran dos servicios habría que sincronizar datos entre ellos.

El bot usa polling (no bloqueante acá: lo arrancamos a mano en vez de
usar run_polling, que toma control del bucle) y el servidor web corre
con uvicorn sobre el mismo bucle de asyncio.
"""
from __future__ import annotations

import asyncio
import os

import uvicorn

from app.bot.telegram_bot import build_app
from app.config import settings
from app.utils.logger import get_logger, setup_logging
from app.web.api import app as web_app

log = get_logger(__name__)


async def main() -> None:
    bot_app = build_app()

    # Arranque manual del bot para no ceder el bucle de eventos:
    # run_polling() lo bloquearía y el servidor web nunca arrancaría.
    await bot_app.initialize()
    await bot_app.start()
    await bot_app.updater.start_polling(drop_pending_updates=True)
    log.info("Bot de Telegram escuchando")

    puerto = int(os.getenv("PORT", "8080"))
    config = uvicorn.Config(
        web_app,
        host="0.0.0.0",
        port=puerto,
        log_level="warning",  # el logging propio ya informa lo importante
        access_log=False,
    )
    servidor = uvicorn.Server(config)
    log.info("Web escuchando en el puerto %s", puerto)

    # Lector del grupo de picks, como tarea de fondo. Si no está
    # configurado, la tarea termina sola sin hacer nada.
    from app.lector.cliente import escuchar

    tarea_lector = asyncio.create_task(escuchar())

    try:
        await servidor.serve()
    finally:
        log.info("Cerrando...")
        tarea_lector.cancel()
        await bot_app.updater.stop()
        await bot_app.stop()
        await bot_app.shutdown()


if __name__ == "__main__":
    setup_logging(settings.log_level)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Detenido por el usuario")
