"""Lector de un grupo de Telegram usando TU cuenta de usuario.

POR QUÉ HACE FALTA ESTO
-----------------------
Ningún bot puede leer un grupo del que no forma parte: es una regla de
Telegram, sin excepciones. Tu cuenta SÍ está en el grupo, así que la
única forma de leerlo automáticamente es con una sesión de usuario
(Telethon), no con un bot.

EL RIESGO, DICHO CLARO
----------------------
La sesión que esto usa da acceso a TODO tu Telegram, no solo a este
grupo. Si alguien accede al servidor, accede a tus chats. Por eso el
módulo está escrito con estas reglas, que no son opcionales:

- SOLO LEE. No manda mensajes, no responde, no se une ni sale de nada.
- SOLO ESE GRUPO. Los mensajes de cualquier otro chat se descartan sin
  guardarse ni registrarse.
- Sin las variables de entorno configuradas, no hace absolutamente
  nada: el resto del proyecto funciona igual.
- La sesión nunca se escribe en disco ni en el repo: viaja como
  variable de entorno.

CÓMO SE CONFIGURA
-----------------
Ver herramientas/generar_sesion.py — se corre UNA vez desde tu propia
computadora o Termux, y produce el valor de TELEGRAM_SESSION.
"""
from __future__ import annotations

import asyncio

from app.config import settings
from app.db.database import guardar_mensaje_grupo
from app.utils.logger import get_logger

log = get_logger(__name__)


def configurado() -> bool:
    """¿Están las tres variables necesarias?"""
    return bool(
        settings.telegram_api_id
        and settings.telegram_api_hash
        and settings.telegram_session
        and settings.telegram_grupo
    )


def _es_el_grupo(chat, esperado: str) -> bool:
    """¿El mensaje vino del grupo configurado y no de otro chat?

    Se compara por username y por id. Cualquier otro origen se descarta:
    la sesión ve TODOS tus chats y no queremos guardar nada más."""
    if chat is None:
        return False

    esperado = esperado.strip().lstrip("@").lower()

    usuario = (getattr(chat, "username", None) or "").lower()
    if usuario and usuario == esperado:
        return True

    if esperado.lstrip("-").isdigit():
        return str(getattr(chat, "id", "")) == esperado

    return False


async def escuchar() -> None:
    """Escucha el grupo y guarda cada mensaje nuevo.

    Se ejecuta como tarea de fondo junto al bot y la web."""
    if not configurado():
        log.info("Lector de grupo no configurado — se omite")
        return

    try:
        from telethon import TelegramClient, events
        from telethon.sessions import StringSession
    except ImportError:
        log.warning("Telethon no está instalado; el lector no arranca")
        return

    grupo = settings.telegram_grupo

    cliente = TelegramClient(
        StringSession(settings.telegram_session),
        int(settings.telegram_api_id),
        settings.telegram_api_hash,
    )

    @cliente.on(events.NewMessage())
    async def _entrante(evento):
        try:
            if not _es_el_grupo(await evento.get_chat(), grupo):
                return  # cualquier otro chat: ni se toca

            texto = (evento.message.message or "").strip()
            if not texto:
                return

            autor = None
            try:
                remitente = await evento.get_sender()
                autor = getattr(remitente, "first_name", None)
            except Exception:
                pass

            await asyncio.to_thread(guardar_mensaje_grupo, grupo, autor, texto)
            log.info("Mensaje del grupo guardado (%d caracteres)", len(texto))
        except Exception:
            log.exception("Error procesando un mensaje del grupo")

    while True:
        try:
            await cliente.start()
            log.info("Lector conectado, escuchando %s", grupo)
            await cliente.run_until_disconnected()
        except Exception:
            log.exception("El lector se cayó; reintento en 60s")

        # Reconectar solo: la consigna es que no pare nunca.
        await asyncio.sleep(60)
