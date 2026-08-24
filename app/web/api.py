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


async def calibracion_api(request: Request) -> JSONResponse:
    """Datos de calibración para el panel al pie de la página.

    Vive en la web porque comparar predicho contra real se entiende de
    un vistazo como barras y es ilegible como lista de números."""
    if not _clave_ok(request.query_params.get("k")):
        return JSONResponse({"detail": "Clave incorrecta"}, status_code=401)

    chat_id = _chat_id()
    if chat_id is None:
        return JSONResponse({"detail": "Falta OWNER_CHAT_ID"}, status_code=500)

    from app.db.database import calibracion, resumen_calibracion

    try:
        from app.db.database import leer_cuotas

        return JSONResponse({
            "resumen": await asyncio.to_thread(resumen_calibracion, chat_id),
            "tramos": await asyncio.to_thread(calibracion, chat_id),
            "cuotas": await asyncio.to_thread(leer_cuotas),
        })
    except Exception:
        log.exception("Error trayendo la calibración")
        return JSONResponse({"detail": "No pude leer la calibración"}, status_code=500)


async def picks_api(request: Request) -> JSONResponse:
    """Picks del día para la pantalla de armado.

    Usa caché de 10 minutos: sin eso, cada visita dispararía un barrido
    completo de la casa de apuestas y de la MLB API."""
    if not _clave_ok(request.query_params.get("k")):
        return JSONResponse({"detail": "Clave incorrecta"}, status_code=401)

    from app.analysis.daily_picks import picks_cacheados
    from app.utils.equipos import partido_corto
    from app.utils.market_labels import nombre_stake_texto
    from app.utils.tiempo import formato_hora_fecha

    try:
        picks = await asyncio.to_thread(picks_cacheados)
    except Exception:
        log.exception("Error trayendo los picks del día")
        return JSONResponse({"detail": "No pude traer los picks"}, status_code=500)

    return JSONResponse({"picks": [
        {
            "id": f"{p.player}|{p.market}|{p.line}",
            "player": p.player,
            "match": partido_corto(p.match),
            "market": nombre_stake_texto(p.market),
            "line": p.line,
            "odds": p.odds,
            "prob": p.our_probability_pct,
            "mercado_paga": p.market_probability_pct,
            "hora": formato_hora_fecha(p.commence_time) if p.commence_time else "",
        }
        for p in picks
    ]})


async def sonadoras_api(request: Request) -> JSONResponse:
    """Soñadoras para la web. Cacheadas 10 minutos: armarlas barre la
    casa de apuestas y la MLB API entera."""
    if not _clave_ok(request.query_params.get("k")):
        return JSONResponse({"detail": "Clave incorrecta"}, status_code=401)

    from app.analysis.combos import sonadoras_cacheadas
    from app.utils.equipos import partido_corto
    from app.utils.market_labels import nombre_stake_texto
    from app.utils.tiempo import formato_hora_fecha

    try:
        combos = await asyncio.to_thread(sonadoras_cacheadas)
    except Exception as exc:
        log.exception("Error armando soñadoras para la web")
        return JSONResponse({"detail": str(exc)}, status_code=500)

    return JSONResponse({"sonadoras": [
        {
            "prob": c.combined_probability_pct,
            "cuota": c.combined_odds,
            "valor": c.expected_value_pct,
            "mismo_partido": c.same_game,
            "legs": [
                {
                    "player": l.player,
                    "match": partido_corto(l.match),
                    "market": nombre_stake_texto(l.market),
                    "line": l.line,
                    "odds": l.odds,
                    "prob": l.probability_pct,
                    "hora": formato_hora_fecha(l.commence_time) if l.commence_time else "",
                }
                for l in c.legs
            ],
        }
        for c in combos
    ]})


async def subir_captura(request: Request) -> JSONResponse:
    """Cargar una apuesta desde la web, sin pasar por Telegram.

    Las imágenes llegan en base64 dentro del JSON a propósito: recibir
    multipart pediría una dependencia nueva, y el proyecto evita sumar
    librerías salvo que hagan falta de verdad."""
    if not _clave_ok(request.query_params.get("k")):
        return JSONResponse({"detail": "Clave incorrecta"}, status_code=401)

    chat_id = _chat_id()
    if chat_id is None:
        return JSONResponse({"detail": "Falta OWNER_CHAT_ID"}, status_code=500)

    import base64

    from app.web.service import guardar_captura

    try:
        cuerpo = await request.json()
        imagenes = [base64.b64decode(i.split(",")[-1]) for i in cuerpo.get("imagenes", [])]
    except Exception:
        return JSONResponse({"detail": "No pude leer las imágenes"}, status_code=400)

    if not imagenes:
        return JSONResponse({"detail": "No mandaste ninguna imagen"}, status_code=400)

    borrador = bool(cuerpo.get("borrador"))
    resultado = await asyncio.to_thread(guardar_captura, chat_id, imagenes, borrador)
    return JSONResponse(resultado, status_code=200 if resultado.get("ok") else 422)


async def mejorar_api(request: Request) -> JSONResponse:
    """Versión segura de una apuesta, para verla en la web."""
    if not _clave_ok(request.query_params.get("k")):
        return JSONResponse({"detail": "Clave incorrecta"}, status_code=401)

    chat_id = _chat_id()
    if chat_id is None:
        return JSONResponse({"detail": "Falta OWNER_CHAT_ID"}, status_code=500)

    from app.web.service import mejorar_ticket

    try:
        resultado = await asyncio.wait_for(
            asyncio.to_thread(mejorar_ticket, chat_id, request.query_params.get("id")),
            timeout=120,
        )
    except asyncio.TimeoutError:
        return JSONResponse({"detail": "Tardó demasiado"}, status_code=504)
    except Exception:
        log.exception("Error mejorando desde la web")
        return JSONResponse({"detail": "No pude analizarla"}, status_code=500)

    return JSONResponse(resultado)


async def creditos_api(request: Request) -> JSONResponse:
    """Créditos que quedan en las APIs de cuotas.

    Se leen de las cabeceras de la última consulta, así que no gastan
    nada: es el número que ya vino con la respuesta anterior. Si todavía
    no se consultó nada en este arranque, viene vacío."""
    if not _clave_ok(request.query_params.get("k")):
        return JSONResponse({"detail": "Clave incorrecta"}, status_code=401)

    from app.odds import parlay, theodds

    return JSONResponse({
        "parlay": parlay.cuota_restante() if parlay.hay_clave() else None,
        "theodds": theodds.cuota_restante(),
    })


async def cuota_manual(request: Request) -> JSONResponse:
    """Corregir a mano la cuota de una apuesta."""
    if not _clave_ok(request.query_params.get("k")):
        return JSONResponse({"detail": "Clave incorrecta"}, status_code=401)

    chat_id = _chat_id()
    if chat_id is None:
        return JSONResponse({"detail": "Falta OWNER_CHAT_ID"}, status_code=500)

    ticket_id = request.query_params.get("id", "")
    cruda = (request.query_params.get("cuota") or "").replace(",", ".").strip()

    try:
        valor = float(cruda)
    except ValueError:
        return JSONResponse({"detail": "Cuota inválida"}, status_code=400)
    if not 1.01 <= valor <= 100000:
        return JSONResponse({"detail": "Cuota fuera de rango"}, status_code=400)

    from app.db.database import fijar_cuota_ticket
    from app.web.service import _ticket_id as calcular_id

    ok = await asyncio.to_thread(
        fijar_cuota_ticket, chat_id, ticket_id, f"{valor:g}", calcular_id
    )
    if not ok:
        return JSONResponse({"detail": "No encontré esa apuesta"}, status_code=404)
    return JSONResponse({"ok": True, "cuota": f"{valor:g}"})


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
        Route("/api/calibracion", calibracion_api),
        Route("/api/picks", picks_api),
        Route("/api/sonadoras", sonadoras_api),
        Route("/api/captura", subir_captura, methods=["POST"]),
        Route("/api/mejorar", mejorar_api),
        Route("/api/cuota", cuota_manual),
        Route("/api/creditos", creditos_api),
    ]
)
