"""Registra las legs ya resueltas para poder medir calibración.

Por qué existe como job y no como efecto secundario de la web: el
registro se disparaba únicamente al abrir la página. Si los partidos
terminaban de madrugada y no entrabas antes de que venciera la
tolerancia, el ticket se borraba sin haberse registrado nunca — por eso
/calibracion no mostraba nada aunque hubiera apuestas resueltas.

Ahora corre solo cada tanto en el servidor, mire el usuario o no.
"""
from __future__ import annotations

import asyncio

from telegram.ext import ContextTypes

from app.db.database import chats_con_apuesta_activa
from app.utils.logger import get_logger

log = get_logger(__name__)


async def registrar_resueltas_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Recalcula el estado de las apuestas guardadas.

    El registro para calibración ocurre dentro de estado_apuestas() al
    detectar que un ticket terminó, así que alcanza con llamarlo: no se
    duplica nada porque la tabla tiene UNIQUE por ticket.
    """
    from app.web.service import estado_apuestas

    try:
        chats = await asyncio.to_thread(chats_con_apuesta_activa)
    except Exception:
        log.exception("No pude listar los chats con apuestas activas")
        return

    for chat_id in chats:
        try:
            await asyncio.to_thread(estado_apuestas, chat_id)
        except Exception:
            # Un chat que falla no puede frenar a los demás.
            log.warning("Fallo recalculando el chat %s", chat_id, exc_info=True)
