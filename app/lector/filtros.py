"""Decide si un mensaje de una fuente hay que guardarlo.

Cada fuente puede pedir condiciones distintas: de un grupo querés todo,
de otro solo lo que publica cierta persona, o solo los mensajes que
traen foto o un link. Sin filtros, seguir varios grupos convierte la
pestaña en un chat entero y deja de servir.
"""
from __future__ import annotations

import re

_LINK = re.compile(r"https?://|t\.me/|www\.", re.I)


def _lista(crudo: str | None) -> list[str]:
    return [x.strip().lower() for x in (crudo or "").split(",") if x.strip()]


def autor_permitido(autor: str | None, permitidos: str | None) -> bool:
    """Sin lista de autores, pasa cualquiera. Con lista, solo esos."""
    lista = _lista(permitidos)
    if not lista:
        return True
    if not autor:
        return False
    bajo = autor.lower()
    # Coincidencia parcial: en Telegram el nombre puede venir con emojis
    # o apellido, y pedir igualdad exacta fallaría casi siempre.
    return any(p in bajo or bajo in p for p in lista)


def tiene_palabra(texto: str, palabras: str | None) -> bool:
    lista = _lista(palabras)
    if not lista:
        return True
    bajo = texto.lower()
    return any(p in bajo for p in lista)


def tiene_link(texto: str) -> bool:
    return bool(_LINK.search(texto or ""))


def pasa(fuente: dict, texto: str, autor: str | None, con_foto: bool) -> bool:
    """¿Este mensaje cumple lo que pide la fuente?"""
    if not autor_permitido(autor, fuente.get("autores")):
        return False
    if fuente.get("requiere_foto") and not con_foto:
        return False
    if fuente.get("requiere_link") and not tiene_link(texto):
        return False
    if not tiene_palabra(texto, fuente.get("palabras")):
        return False
    return True
