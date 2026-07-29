"""Configuración centralizada de logging para todo el bot."""
import logging
import sys


def setup_logging(level: str = "INFO") -> None:
    """Configura el logging global de la aplicación.

    Silencia logs muy verbosos de librerías externas (httpx, telegram)
    para que la consola quede legible.
    """
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
