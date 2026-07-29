"""Helpers para interactuar con Telegram sin pisar sus límites ni
romper el parseo de Markdown.

Dos problemas que resuelve este módulo:

1. Límite de longitud: Telegram rechaza mensajes de más de 4096
   caracteres con BadRequest. Hay que trocear.

2. Markdown desbalanceado: todo lo que viene de la IA (nombres de
   jugadores, equipos, mercados leídos de una captura) puede contener
   '*' o '_'. Si esos caracteres quedan sin escapar, Telegram rechaza
   el mensaje ENTERO y el usuario no ve nada. Por eso hay que escapar
   el contenido dinámico antes de meterlo en texto con formato.
"""
from telegram import Message

TELEGRAM_MAX_LEN = 4096
# Dejamos margen para no rozar el límite exacto
SAFE_LEN = 3900

# Caracteres con significado en el Markdown (legacy) de Telegram
_MD_SPECIAL = ("*", "_", "`", "[")


def escape_md(text: str | None) -> str:
    """Escapa caracteres especiales de Markdown en contenido dinámico.

    Úsalo SIEMPRE con valores que vengan de la IA, de la API o del
    usuario — nunca con el formato que escribimos nosotros a propósito.
    """
    if text is None:
        return ""
    result = str(text)
    for ch in _MD_SPECIAL:
        result = result.replace(ch, f"\\{ch}")
    return result


def split_message(text: str, limit: int = SAFE_LEN) -> list[str]:
    """Parte `text` en trozos que entren en Telegram.

    Prioriza cortar entre bloques (separados por línea en blanco) para
    no partir una leg o una prop al medio. Si un bloque suelto ya supera
    el límite, lo corta a la fuerza — es feo, pero es mejor que un
    BadRequest donde el usuario no recibe nada.
    """
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    current = ""

    for block in text.split("\n\n"):
        # Un bloque que por sí solo no entra: lo cortamos duro.
        if len(block) > limit:
            if current:
                chunks.append(current)
                current = ""
            for i in range(0, len(block), limit):
                chunks.append(block[i : i + limit])
            continue

        candidate = f"{current}\n\n{block}" if current else block
        if len(candidate) > limit:
            if current:
                chunks.append(current)
            current = block
        else:
            current = candidate

    if current:
        chunks.append(current)
    return chunks


async def send_long_message(message: Message, text: str, parse_mode: str | None = None) -> None:
    """Envía `text` partiéndolo en varios mensajes si hace falta."""
    for chunk in split_message(text):
        await message.reply_text(chunk, parse_mode=parse_mode)


async def edit_then_send_rest(processing_msg: Message, text: str, parse_mode: str | None = "Markdown") -> None:
    """Edita el mensaje de 'Analizando...' con el resultado. Si no entra
    en un solo mensaje, manda el resto como mensajes nuevos."""
    chunks = split_message(text)
    await processing_msg.edit_text(chunks[0], parse_mode=parse_mode)
    for chunk in chunks[1:]:
        await processing_msg.reply_text(chunk, parse_mode=parse_mode)
