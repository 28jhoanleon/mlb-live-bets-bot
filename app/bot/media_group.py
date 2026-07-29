"""Agrupación de capturas múltiples (álbumes de Telegram).

Problema que resuelve: una combinada de 8 legs no entra en una sola
captura. El usuario manda 2 o 3 fotos, pero Telegram las entrega como
mensajes SEPARADOS, así que el bot las analizaba de a una y cada una
pisaba a la anterior.

Cómo se resuelve: cuando el usuario manda varias fotos juntas (álbum),
todas llegan con el mismo `media_group_id`. Guardamos las imágenes en un
buffer con esa clave, esperamos un momento a que lleguen todas, y recién
ahí analizamos el conjunto como UNA sola apuesta.

El buffer vive en memoria porque es efímero por naturaleza: dura los dos
segundos entre la primera y la última foto del álbum.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from app.utils.logger import get_logger

log = get_logger(__name__)

# Cuánto esperamos desde la última foto recibida antes de procesar.
# Telegram manda las fotos de un álbum casi juntas; 2 segundos alcanza
# de sobra y no se siente como demora.
_VENTANA_SEGUNDOS = 2.0


@dataclass
class GrupoDeImagenes:
    imagenes: list[bytes] = field(default_factory=list)
    tarea: asyncio.Task | None = None


_grupos: dict[str, GrupoDeImagenes] = {}


def agregar_imagen(media_group_id: str, imagen: bytes) -> GrupoDeImagenes:
    grupo = _grupos.setdefault(media_group_id, GrupoDeImagenes())
    grupo.imagenes.append(imagen)
    return grupo


def cancelar_espera(media_group_id: str) -> None:
    """Reinicia el temporizador: llegó otra foto del mismo álbum."""
    grupo = _grupos.get(media_group_id)
    if grupo and grupo.tarea and not grupo.tarea.done():
        grupo.tarea.cancel()


def registrar_espera(media_group_id: str, tarea: asyncio.Task) -> None:
    grupo = _grupos.get(media_group_id)
    if grupo:
        grupo.tarea = tarea


def recuperar_y_limpiar(media_group_id: str) -> list[bytes]:
    grupo = _grupos.pop(media_group_id, None)
    return grupo.imagenes if grupo else []


async def esperar_resto_del_album() -> None:
    await asyncio.sleep(_VENTANA_SEGUNDOS)


def merge_analyses(analisis: list[dict]) -> dict:
    """Fusiona el análisis de varias capturas en una sola apuesta.

    Deduplica legs repetidas: si dos capturas se superponen (algo muy
    común al scrollear una combinada larga), la misma leg aparecería dos
    veces y arruinaría el conteo de "X de Y cumplidas".
    """
    legs: list[dict] = []
    vistas: set[tuple] = set()
    is_live = False

    for a in analisis:
        if a.get("is_live"):
            is_live = True
        for leg in a.get("legs", []):
            clave = (
                str(leg.get("player", "")).strip().lower(),
                str(leg.get("market", "")).strip().lower(),
                str(leg.get("line", "")).strip().lower(),
            )
            if clave in vistas:
                continue
            vistas.add(clave)
            legs.append(leg)

    return {
        "is_parlay": len(legs) > 1,
        "is_live": is_live,
        "legs": legs,
    }
