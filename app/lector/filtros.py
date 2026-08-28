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


# Dominios conocidos de cada casa. Alcanza con nombrar la casa
# ("stake") y no hace falta acordarse de todos sus dominios: Stake usa
# varios según el país, y pba.stake.bet.ar es el de Buenos Aires.
_CASAS = {
    # SOLO el Stake de Buenos Aires. Las otras variantes (stake.com,
    # stake.bet) son de otros países y no sirven acá: un cupón de esas
    # no se puede copiar desde Argentina.
    "stake": ("pba.stake",),
    "pba": ("pba.stake",),
    "bet365": ("bet365.com", "bet365.bet.ar", "bet365"),
}


def tiene_casa(texto: str, casas: str | None) -> bool:
    """¿El mensaje trae un link de alguna de las casas pedidas?

    Sirve para quedarse solo con los picks que traen el cupón para
    copiar, y descartar los comentarios sueltos."""
    pedidas = _lista(casas)
    if not pedidas:
        return True

    bajo = (texto or "").lower()
    for casa in pedidas:
        # Por nombre conocido, o por si escribiste el dominio directo.
        for dominio in _CASAS.get(casa, (casa,)):
            if dominio in bajo:
                return True
    return False


def pasa(fuente: dict, texto: str, autor: str | None, con_foto: bool) -> bool:
    """¿Este mensaje cumple lo que pide la fuente?"""
    if not autor_permitido(autor, fuente.get("autores")):
        return False

    if fuente.get("solo_apuestas"):
        # Reaccionaste a alguien: de ahí en más se sigue lo suyo que
        # PAREZCA apuesta -- foto o link, cualquiera de las dos alcanza.
        # Distinto de requiere_foto/requiere_link (configurados a mano),
        # que exigen cada condición por separado.
        if not (con_foto or tiene_link(texto)):
            return False
    else:
        if fuente.get("requiere_foto") and not con_foto:
            return False
        if fuente.get("requiere_link") and not tiene_link(texto):
            return False

    if not tiene_palabra(texto, fuente.get("palabras")):
        return False
    if not tiene_casa(texto, fuente.get("casas")):
        return False
    return True
