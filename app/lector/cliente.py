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
from app.db.database import (
    agregar_autor_a_fuente,
    agregar_fuente,
    carpeta_fotos,
    guardar_mensaje_grupo,
    listar_fuentes,
)
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


def _nombre_de(remitente) -> str | None:
    """El nombre para mostrar, probando varias fuentes.

    `first_name` falla para admins que postean como anónimos (aparecen
    como un chat/canal, no como usuario) -- ahí Telegram da `.title` en
    vez de `.first_name`. Sin este respaldo, esas personas quedaban
    guardadas como "id 12345", que no dice nada a simple vista aunque
    el filtro funcione bien por dentro.
    """
    nombre = getattr(remitente, "first_name", None)
    if nombre:
        apellido = getattr(remitente, "last_name", None)
        return f"{nombre} {apellido}" if apellido else nombre

    titulo = getattr(remitente, "title", None)
    if titulo:
        return titulo

    usuario = getattr(remitente, "username", None)
    if usuario:
        return f"@{usuario}"

    return None


def _texto_con_links(mensaje) -> str:
    """El texto visible, más cualquier link que venga ESCONDIDO detrás
    de una palabra corta.

    Telegram permite que un texto como "x20" lleve una URL invisible
    atrás (como un link de HTML). `mensaje.message` solo trae el texto
    que se ve -- la URL real no está ahí en ningún lado. Sin esto, un
    cupón compartido así ("x20" con el link del cupón escondido detrás)
    se guardaba sin el link: no se veía, no era clickeable, y tampoco
    lo detectaban los filtros de casa/link (que buscan el dominio en el
    texto y ahí no estaba)."""
    texto = (mensaje.message or "").strip()
    entidades = getattr(mensaje, "entities", None) or []
    ocultas = []
    for e in entidades:
        url = getattr(e, "url", None)  # solo lo tienen los links con texto propio
        if url and url not in texto and url not in ocultas:
            ocultas.append(url)
    if ocultas:
        texto = (texto + "\n" + "\n".join(ocultas)).strip()
    return texto


async def _mi_reaccion(cliente, update, yo_id: int, GetMessageReactionsListRequest, BroadcastForbiddenError) -> str | None:
    """Qué emoji puse yo en este mensaje, si puse alguno.

    En grupos grandes (miles de miembros, como el de MLB) Telegram
    manda la actualización "resumida": solo los conteos totales, sin
    decir quién reaccionó -- `recent_reactions` llega vacío justo en
    los grupos donde esto más se usa. Por eso primero se intenta ahí
    (rápido) y si no hay nada se pide la lista completa de reacciones
    de ESE mensaje puntual, que sí la trae siempre.
    """
    reacciones = getattr(update.reactions, "recent_reactions", None) or []
    for r in reacciones:
        if getattr(getattr(r, "peer_id", None), "user_id", None) == yo_id:
            return _normalizar_emoji(getattr(r.reaction, "emoticon", None))

    try:
        # update.peer es un Peer "crudo" (solo el id); la consulta
        # necesita un InputPeer resuelto, con el access_hash que
        # Telegram exige para identificar el chat de forma segura. Sin
        # este paso la consulta tira una excepción, se cae al except de
        # abajo, y la reacción queda sin efecto en silencio -- daba la
        # sensación de que "no pasaba nada" al reaccionar.
        #
        # get_input_entity() solo mira la caché local de la sesión. Si
        # el chat en cuestión todavía no pasó por esa caché (por
        # ejemplo, un grupo donde la sesión no tuvo actividad reciente),
        # falla aunque la cuenta SÍ sea miembro. get_entity() es más
        # lento pero además consulta a Telegram si hace falta, así que
        # sirve de segundo intento antes de rendirse. Esto explicaría
        # que funcione en un grupo (ya en caché) y no en otro (todavía
        # no visto por esta sesión).
        try:
            peer_resuelto = await cliente.get_input_entity(update.peer)
        except Exception:
            log.info("Peer no estaba en caché, pruebo resolverlo contra la API")
            entidad = await cliente.get_entity(update.peer)
            peer_resuelto = await cliente.get_input_entity(entidad)

        resultado = await cliente(GetMessageReactionsListRequest(
            peer=peer_resuelto, id=update.msg_id, limit=100,
        ))
    except BroadcastForbiddenError:
        # Esto es un CANAL de difusión, no un grupo -- Telegram no deja
        # pedir quién reaccionó ahí, ni siquiera siendo miembro. No es
        # un bug de acá, es una restricción real de la plataforma:
        # reaccionar para seguir a alguien solo funciona en grupos.
        log.info(
            "Reacción en un canal (chat_id=%s): Telegram no expone quién "
            "reacciona en canales, así que esto no se puede resolver. Para "
            "canales, usá /fuentes add en vez de reaccionar.",
            getattr(update.peer, "channel_id", None),
        )
        return None
    except Exception:
        log.exception(
            "No pude pedir la lista completa de reacciones (chat_id=%s, msg_id=%s)",
            getattr(update.peer, "channel_id", None) or getattr(update.peer, "chat_id", None),
            update.msg_id,
        )
        return None

    for r in getattr(resultado, "reactions", []):
        if getattr(getattr(r, "peer_id", None), "user_id", None) == yo_id:
            return _normalizar_emoji(getattr(r.reaction, "emoticon", None))
    return None


def _normalizar_emoji(emoji: str | None) -> str | None:
    """Saca el selector de variante (U+FE0F) si vino pegado.

    Telegram a veces manda el emoji con ese carácter invisible agregado
    y a veces sin él; sin normalizar, "🔥" y "🔥\ufe0f" son strings
    distintos y la comparación contra los emojis configurados falla
    aunque sean el mismo emoji a simple vista.
    """
    if emoji is None:
        return None
    return emoji.replace("\ufe0f", "")


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
    return {_normalizar_emoji(e.strip()) for e in crudo.split(",") if e.strip()}


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
    from telethon.errors import BroadcastForbiddenError
    from telethon.tl.functions.messages import GetMessageReactionsListRequest
    from telethon.tl.types import UpdateMessageReactions

    yo_id: int | None = None

    @cliente.on(events.Raw(UpdateMessageReactions))
    async def _reaccion(update):
        nonlocal yo_id
        # Primera línea de todas, a propósito: si esto no aparece en
        # los logs, el handler ni siquiera se está disparando para ese
        # chat -- muy distinto de "se disparó pero algo falló adentro".
        log.info(
            "Reacción cruda recibida (chat_id=%s, msg_id=%s)",
            getattr(update.peer, "channel_id", None) or getattr(update.peer, "chat_id", None),
            update.msg_id,
        )
        try:
            emojis = _emojis_configurados()
            if not emojis:
                log.info("Sin emojis configurados, se ignora")
                return

            if yo_id is None:
                yo_id = (await cliente.get_me()).id

            emoji = await _mi_reaccion(cliente, update, yo_id, GetMessageReactionsListRequest, BroadcastForbiddenError)
            if emoji is None:
                log.info("No pude identificar cuál emoji puse yo (o no reaccioné yo)")
                return
            if emoji not in emojis:
                log.info("Reacción %r no está en la lista configurada %s", emoji, emojis)
                return

            mensaje = await cliente.get_messages(update.peer, ids=update.msg_id)
            if mensaje is None:
                log.info("get_messages no devolvió el mensaje")
                return

            texto = _texto_con_links(mensaje)
            con_foto = bool(getattr(mensaje, "photo", None))
            if not texto and not con_foto:
                return

            autor = None
            autor_id = None
            try:
                remitente = await mensaje.get_sender()
                autor = _nombre_de(remitente)
                autor_id = getattr(remitente, "id", None)
            except Exception:
                pass

            chat = await mensaje.get_chat()
            fuentes = await asyncio.to_thread(listar_fuentes)
            fuente = _fuente_de(chat, fuentes)

            # Reaccionar significa "seguí a esta persona de acá en más":
            # de este grupo, sus mensajes con foto o link (los que
            # parecen apuesta) se guardan solos, sin reaccionar de nuevo
            # cada vez. Se guarda por ID, no por nombre -- el nombre es
            # ambiguo (dos personas pueden llamarse "Leandro"), el id no.
            handle = getattr(chat, "username", None) or str(getattr(chat, "id", ""))
            if fuente is None:
                nombre = getattr(chat, "title", None) or handle
                ids = f"{autor_id}:{autor or ''}" if autor_id is not None else ""
                await asyncio.to_thread(
                    agregar_fuente, nombre, handle, autor or "", False, False,
                    "", "", True, ids,
                )
                origen = nombre
            else:
                if autor:
                    await asyncio.to_thread(
                        agregar_autor_a_fuente, fuente["grupo"], autor, autor_id,
                    )
                origen = fuente["nombre"]

            foto = await _descargar_si_hay(cliente, mensaje) if con_foto else None

            await asyncio.to_thread(
                guardar_mensaje_grupo, origen, autor, texto or "(imagen)", foto
            )
            log.info(
                "Guardado por reacción %s de %s en %s -- seguimiento activado",
                emoji, autor or "?", origen,
            )
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

            texto = _texto_con_links(evento.message)
            if not texto:
                return

            autor = None
            autor_id = None
            try:
                remitente = await evento.get_sender()
                autor = _nombre_de(remitente)
                autor_id = getattr(remitente, "id", None)
            except Exception:
                pass

            con_foto = bool(getattr(evento.message, "photo", None))
            if not pasa(fuente, texto, autor, con_foto, autor_id):
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
