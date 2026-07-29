"""Servidor web: sirve la página y expone el estado de las apuestas.

Usa Starlette en vez de FastAPI a propósito. FastAPI arrastra pydantic,
que tiene una parte compilada en Rust (`pydantic-core`) y NO tiene
paquetes precompilados para Android: en Termux la instalación falla.
Starlette es Python puro, es lo que FastAPI usa por debajo, y para tres
rutas simples no perdemos nada.

Corre en el MISMO proceso que el bot, así que hay un solo servicio en
Railway, una sola base de datos y una sola copia de la lógica.

Acceso: como es una herramienta personal, se protege con una clave en la
URL (`?k=...`). No es un sistema de usuarios; es para que la dirección
no quede abierta a cualquiera que la adivine.
"""
from __future__ import annotations

import os
from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Route

from app.db.database import init_db
from app.utils.logger import get_logger
from app.web.service import estado_apuestas

log = get_logger(__name__)

ESTATICOS = Path(__file__).parent / "static"


def _clave_ok(k: str | None) -> bool:
    esperada = os.getenv("WEB_KEY", "").strip()
    # Sin WEB_KEY configurada dejamos pasar: cómodo para probar en local.
    if not esperada:
        return True
    return k == esperada


def _chat_id() -> int | None:
    valor = os.getenv("OWNER_CHAT_ID", "").strip()
    if not valor:
        return None
    try:
        return int(valor)
    except ValueError:
        return None


async def health(request: Request) -> JSONResponse:
    return JSONResponse({"ok": True})


async def bets(request: Request) -> JSONResponse:
    if not _clave_ok(request.query_params.get("k")):
        return JSONResponse({"detail": "Clave incorrecta"}, status_code=401)

    chat_id = _chat_id()
    if chat_id is None:
        return JSONResponse(
            {"detail": "Falta OWNER_CHAT_ID. Usá /miid en el bot para saber el tuyo."},
            status_code=500,
        )

    try:
        return JSONResponse(estado_apuestas(chat_id))
    except Exception:
        log.exception("Error armando el estado de apuestas para la web")
        return JSONResponse({"detail": "No pude leer las apuestas"}, status_code=500)


async def index(request: Request) -> FileResponse:
    return FileResponse(ESTATICOS / "index.html")


async def _al_arrancar() -> None:
    # Idempotente (CREATE TABLE IF NOT EXISTS). Lo llamamos también acá
    # para que la web funcione aunque se levante sola, sin el bot.
    init_db()


app = Starlette(
    on_startup=[_al_arrancar],
    routes=[
        Route("/", index),
        Route("/health", health),
        Route("/api/bets", bets),
    ]
)
