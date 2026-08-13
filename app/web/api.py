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

import asyncio
import contextlib
import os
from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Route

from app.analysis.probability import ProbabilityError
from app.db.database import init_db
from app.utils.logger import get_logger
from app.web.service import detalle_leg, estado_apuestas

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
        # estado_apuestas hace varias llamadas de red BLOQUEANTES (requests,
        # no httpx/aiohttp) a la MLB Stats API. Este proceso corre el bot y
        # la web sobre el mismo event loop: sin to_thread, esas llamadas
        # congelan TODO -bot incluido- mientras duran. Con varias legs
        # cayendo al histórico (2 llamadas bloqueantes cada una) esto se
        # nota como la página tardando mucho o directamente cortándose.
        resultado = await asyncio.to_thread(estado_apuestas, chat_id)
        return JSONResponse(resultado)
    except Exception:
        log.exception("Error armando el estado de apuestas para la web")
        return JSONResponse({"detail": "No pude leer las apuestas"}, status_code=500)


async def leg_detail(request: Request) -> JSONResponse:
    if not _clave_ok(request.query_params.get("k")):
        return JSONResponse({"detail": "Clave incorrecta"}, status_code=401)

    player = request.query_params.get("player", "")
    market = request.query_params.get("market", "")
    line = request.query_params.get("line", "")

    try:
        resultado = await asyncio.to_thread(detalle_leg, player, market, line)
        return JSONResponse(resultado)
    except ProbabilityError as e:
        return JSONResponse({"detail": str(e)}, status_code=404)
    except Exception:
        log.exception("Error armando el detalle de la leg")
        return JSONResponse({"detail": "No pude traer el detalle de este jugador"}, status_code=500)


async def ticket_accion(request: Request) -> JSONResponse:
    """Confirmar o descartar un ticket desde la web.

    Es lo que hace útil ver los borradores acá: se comparan cómodo y se
    decide en el momento, sin volver a Telegram."""
    if not _clave_ok(request.query_params.get("k")):
        return JSONResponse({"detail": "Clave incorrecta"}, status_code=401)

    chat_id = _chat_id()
    if chat_id is None:
        return JSONResponse({"detail": "Falta OWNER_CHAT_ID"}, status_code=500)

    ticket_id = request.query_params.get("id", "")
    accion = request.query_params.get("accion", "")
    if not ticket_id or accion not in ("jugada", "descartar"):
        return JSONResponse({"detail": "Pedido inválido"}, status_code=400)

    from app.db.database import confirmar_borrador, descartar_ticket
    from app.web.service import _ticket_id as calcular_id

    try:
        if accion == "jugada":
            ok = await asyncio.to_thread(confirmar_borrador, chat_id, ticket_id, calcular_id)
        else:
            ok = await asyncio.to_thread(descartar_ticket, chat_id, ticket_id, calcular_id)
    except Exception:
        log.exception("Error aplicando la acción sobre el ticket")
        return JSONResponse({"detail": "No pude aplicar el cambio"}, status_code=500)

    if not ok:
        return JSONResponse({"detail": "No encontré esa apuesta"}, status_code=404)
    return JSONResponse({"ok": True})


async def index(request: Request) -> FileResponse:
    return FileResponse(ESTATICOS / "index.html")


@contextlib.asynccontextmanager
async def _ciclo_de_vida(app: Starlette):
    # init_db es idempotente (CREATE TABLE IF NOT EXISTS). Lo llamamos
    # también acá para que la web funcione aunque se levante sola.
    init_db()
    yield


app = Starlette(
    lifespan=_ciclo_de_vida,
    routes=[
        Route("/", index),
        Route("/health", health),
        Route("/api/bets", bets),
        Route("/api/leg-detail", leg_detail),
        Route("/api/ticket-accion", ticket_accion),
    ]
)
