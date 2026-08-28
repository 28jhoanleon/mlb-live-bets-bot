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
from app.db.database import carpeta_fotos, guardar_mensaje_grupo, listar_fuentes
from app.lector.filtros import pasa
from app.utils.logger import get_logger

log = get_logger(__name__)


def configurado() -> bool:
    """¿Están las credenciales? Las fuentes se configuran aparte, desde
    el bot, así que acá solo importan las tres de la sesión."""
    return bool(
        settings.telegram_api_id
        and settings.telegram_api_hash
        and settings.telegram_session
    )


async def _mi_reaccion(cliente, update, yo_id: int, GetMessageReactionsListRequest) -> str | None:
    """Qué emoji puse yo en este mensaje, si puse alguno.

    En grupos grandes (miles de miembros, como el de MLB) Telegram
    manda la actualización "resumida": solo los conteos totales, sin
    decir quién reaccionó -- `recent_reactions` llega vacío justo en
    los grupos donde esto más se usa. Por eso primero se intenta ahí
    (rápido) y si no hay nada se pide la lista completa de reacciones
    de ESE mensaje puntual, que sí la trae siempre."""
    reacciones = getattr(update.reactions, "recent_reactions", None) or []
    for r in reacciones:
        if getattr(getattr(r, "peer_id", None), "user_id", None) == yo_id:
            return getattr(r.reaction, "emoticon", None)

    try:
        resultado = await cliente(GetMessageReactionsListRequest(
            peer=update.peer, id=update.msg_id, limit=100,
        ))
    except Exception:
        log.exception("No pude pedir la lista completa de reacciones")
        return None

    for r in getattr(resultado, "reactions", []):
        if getattr(getattr(r, "peer_id", None), "user_id", None) == yo_id:
            return getattr(r.reaction, "emoticon", None)
    return None


async def _descargar_si_hay(cliente, mensaje) -> str | None:
    """Baja la foto a disco y devuelve la ruta. Si falla, el mensaje se
    guarda igual pero sin imagen -- una foto que no bajó no puede
    perder el texto del pick."""
    import os
    import uuid

    try:
        carpeta = carpeta_fotos()
        destino = os.path.join(carpeta, f"{uuid.uuid4().hex}.jpg")
        ruta = await cliente.download_media(mensaje, file=destino)
        return ruta
    except Exception:
        log.exception("No pude descargar la foto del mensaje")
        return None


def _emojis_configurados() -> set[str]:
    """Emojis que marcan un mensaje para guardar.

    Configurables por variable de entorno; por defecto los que uno usa
    naturalmente para señalar algo interesante."""
    crudo = (settings.telegram_emojis or "⭐,🔥,✅,👍").strip()
    return {e.strip() for e in crudo.split(",") if e.strip()}


def _fuente_de(chat, fuentes: list[dict]) -> dict | None:
    """Busca a qué fuente configurada pertenece este chat.

    Si no pertenece a ninguna, el mensaje se descarta sin tocarse: la
    sesión ve TODOS los chats del usuario y solo queremos los elegidos.
    """
    for fuente in fuentes:
        if _es_el_grupo(chat, fuente["grupo"]):
            return fuente
    return None


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

    cliente = TelegramClient(
        StringSession(settings.telegram_session),
        int(settings.telegram_api_id),
        settings.telegram_api_hash,
    )

    # --- Captura por reacción ---------------------------------------
    #
    # Reaccionar a un mensaje con un emoji lo guarda, aunque no cumpla
    # ningún filtro. Es curación manual sin fricción: leés el grupo como
    # siempre y marcás lo que te sirve con un toque.
    #
    # Solo cuentan TUS reacciones. Que otro reaccione no guarda nada.
    from telethon.tl.functions.messages import GetMessageReactionsListRequest
    from telethon.tl.types import UpdateMessageReactions

    yo_id: int | None = None

    @cliente.on(events.Raw(UpdateMessageReactions))
    async def _reaccion(update):
        nonlocal yo_id
        try:
            emojis = _emojis_configurados()
            if not emojis:
                return

            if yo_id is None:
                yo_id = (await cliente.get_me()).id

            emoji = await _mi_reaccion(cliente, update, yo_id, GetMessageReactionsListRequest)
            if emoji is None or emoji not in emojis:
                return

            mensaje = await cliente.get_messages(update.peer, ids=update.msg_id)
            if mensaje is None:
                return

            texto = (mensaje.message or "").strip()
            con_foto = bool(getattr(mensaje, "photo", None))
            if not texto and not con_foto:
                return

            autor = None
            try:
                remitente = await mensaje.get_sender()
                autor = getattr(remitente, "first_name", None)
            except Exception:
                pass

            fuentes = await asyncio.to_thread(listar_fuentes)
            fuente = _fuente_de(await mensaje.get_chat(), fuentes)
            origen = fuente["nombre"] if fuente else "marcado con reacción"

            foto = await _descargar_si_hay(cliente, mensaje) if con_foto else None

            await asyncio.to_thread(
                guardar_mensaje_grupo, origen, autor, texto or "(imagen)", foto
            )
            log.info("Guardado por reacción %s desde %s", emoji, origen)
        except Exception:
            log.exception("Error procesando una reacción")

    @cliente.on(events.NewMessage())
    async def _entrante(evento):
        try:
            # Las fuentes se leen en cada mensaje para que agregar o
            # quitar una desde el bot tenga efecto sin reiniciar.
            fuentes = await asyncio.to_thread(listar_fuentes)
            if not fuentes:
                return

            fuente = _fuente_de(await evento.get_chat(), fuentes)
            if fuente is None:
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

            con_foto = bool(getattr(evento.message, "photo", None))
            if not pasa(fuente, texto, autor, con_foto):
                return

            foto = await _descargar_si_hay(cliente, evento.message) if con_foto else None

            await asyncio.to_thread(
                guardar_mensaje_grupo, fuente["nombre"], autor, texto, foto
            )
            log.info("Guardado de %s (%d caracteres)", fuente["nombre"], len(texto))
        except Exception:
            log.exception("Error procesando un mensaje del grupo")

    while True:
        try:
            await cliente.start()
            fuentes = await asyncio.to_thread(listar_fuentes)
            log.info(
                "Lector conectado · %d fuente(s): %s",
                len(fuentes), ", ".join(f["nombre"] for f in fuentes) or "ninguna",
            )
            await cliente.run_until_disconnected()
        except Exception:
            log.exception("El lector se cayó; reintento en 60s")

        # Reconectar solo: la consigna es que no pare nunca.
        await asyncio.sleep(60)
