"""Cliente para ParlayAPI (https://parlay-api.com).

Misma interfaz pública que app/odds/theodds.py, para poder cambiar de
proveedor sin tocar la lógica de negocio.

Por qué se agregó: The Odds API cobra una consulta POR PARTIDO, así que
un barrido de 12 partidos gastaba 12 créditos y nos dejó la cuota en
negativo. Acá UNA llamada de 3 créditos trae todos los mercados de todos
los books para todo el MLB. Además publica `player_hits_runs_rbis`, que
es el mercado que más aparece en las capturas de Stake ("Golpes +
Carreras + Carreras Remolcadas").

La respuesta viene con OTRA forma -una fila por (book, jugador, mercado,
línea)- así que se traduce al formato que ya consume el resto del
proyecto, en vez de propagar el cambio hacia adentro.
"""
from __future__ import annotations

from typing import Any

import requests

from app.config import settings
from app.utils.logger import get_logger

log = get_logger(__name__)

_BASE_URL = "https://parlay-api.com/v1"
_SPORT_KEY = "baseball_mlb"
_TIMEOUT = 15

_cuota_restante: int | None = None


class ParlayClientError(Exception):
    """Error al comunicarse con ParlayAPI."""


def hay_clave() -> bool:
    return bool(settings.parlay_api_key)


def cuota_restante() -> int | None:
    return _cuota_restante


def _get(path: str, params: dict[str, Any] | None = None) -> Any:
    if not settings.parlay_api_key:
        raise ParlayClientError("Falta PARLAY_API_KEY.")

    try:
        resp = requests.get(
            f"{_BASE_URL}{path}",
            params=params or {},
            headers={"X-API-Key": settings.parlay_api_key},
            timeout=_TIMEOUT,
        )
        if resp.status_code == 401:
            raise ParlayClientError("ParlayAPI rechazó la clave (401).")
        if resp.status_code == 403:
            raise ParlayClientError("Se agotaron los créditos de ParlayAPI (403).")
        if resp.status_code == 429:
            raise ParlayClientError("ParlayAPI pidió bajar el ritmo (429).")
        resp.raise_for_status()

        restantes = resp.headers.get("x-requests-remaining")
        if restantes is not None:
            try:
                global _cuota_restante
                _cuota_restante = int(restantes)
                if _cuota_restante < 50:
                    log.warning("Quedan %s créditos en ParlayAPI", restantes)
            except ValueError:
                pass

        return resp.json()
    except ParlayClientError:
        raise
    except requests.RequestException as exc:
        raise ParlayClientError(f"No pude consultar ParlayAPI: {exc}") from exc


def get_events() -> list[dict[str, Any]]:
    """Partidos del día. Gratis (0 créditos)."""
    datos = _get(f"/sports/{_SPORT_KEY}/events")
    return datos if isinstance(datos, list) else []


def get_all_props(markets: str | None = None) -> list[dict[str, Any]]:
    """TODOS los props del MLB en una sola llamada (3 créditos).

    Ésta es la ventaja concreta sobre The Odds API, donde había que
    pedir partido por partido."""
    params: dict[str, Any] = {"limit": 10000, "oddsFormat": "decimal"}
    if markets:
        params["markets"] = markets
    datos = _get(f"/sports/{_SPORT_KEY}/props", params)
    return datos if isinstance(datos, list) else []


# ParlayAPI nombra TODOS los mercados con el prefijo `player_`, mientras
# que el resto del proyecto distingue `batter_` de `pitcher_`. Sin
# traducir esto, "player_runs" (carreras ANOTADAS, de bateo) aplicado a
# un pitcher se interpretaba como carreras PERMITIDAS: el bot calculaba
# "permite >=1 carrera" (casi siempre) y lo comparaba contra el precio de
# "el pitcher anota una carrera" (casi nunca). Ventaja falsa enorme, y el
# buscador de soñadoras elegía sistemáticamente esos casos.
_MERCADOS_BATEO = {
    "player_hits": "batter_hits",
    "player_home_runs": "batter_home_runs",
    "player_rbis": "batter_rbis",
    "player_runs": "batter_runs_scored",
    "player_total_bases": "batter_total_bases",
    "player_singles": "batter_singles",
    "player_doubles": "batter_doubles",
    "player_triples": "batter_triples",
    "player_hits_runs_rbis": "batter_hits_runs_rbis",
    "player_stolen_bases": "batter_stolen_bases",
}

_MERCADOS_PITCHEO = {
    "player_pitcher_outs": "pitcher_outs",
    "player_hits_allowed": "pitcher_hits_allowed",
    "player_earned_runs": "pitcher_earned_runs",
}

# Genuinamente ambiguos: los ponches de un pitcher son los que reparte;
# los de un bateador, los que se come. Se dejan sin prefijo para que se
# resuelvan por el rol real del jugador, que ahí sí es la señal correcta.
_MERCADOS_AMBIGUOS = {"player_strikeouts", "player_walks"}


def traducir_mercado(clave: str) -> str | None:
    """Pasa una clave de ParlayAPI al vocabulario interno.

    Devuelve None si el mercado no lo sabemos evaluar: preferible
    descartarlo que interpretarlo mal."""
    if clave in _MERCADOS_BATEO:
        return _MERCADOS_BATEO[clave]
    if clave in _MERCADOS_PITCHEO:
        return _MERCADOS_PITCHEO[clave]
    if clave in _MERCADOS_AMBIGUOS:
        return clave
    return None


def _a_decimal(precio: Any) -> float | None:
    """ParlayAPI puede devolver precio americano; se normaliza a decimal,
    que es lo que usa el resto del proyecto."""
    try:
        p = float(precio)
    except (TypeError, ValueError):
        return None
    if -100 < p < 100 and p != 0:
        # Ya viene en decimal (las cuotas decimales válidas son > 1).
        return p if p > 1 else None
    if p > 0:
        return round(p / 100 + 1, 3)
    return round(100 / abs(p) + 1, 3)


def props_por_evento(markets: str | None = None) -> dict[str, dict[str, Any]]:
    """Agrupa los props por partido, en el formato que ya consume
    daily_picks: {event_id: {"event": {...}, "props": {bookmakers: [...]}}}.

    Traducir acá y no adentro mantiene el cambio de proveedor contenido
    en un solo archivo.
    """
    filas = get_all_props(markets)

    por_evento: dict[str, dict[str, Any]] = {}
    for fila in filas:
        eid = fila.get("canonical_event_id")
        if not eid:
            continue

        entrada = por_evento.setdefault(eid, {
            "event": {
                "id": eid,
                "home_team": fila.get("home_team"),
                "away_team": fila.get("away_team"),
                "commence_time": fila.get("commence_time"),
            },
            "_books": {},
        })

        book = fila.get("bookmaker") or "?"
        jugador = fila.get("player")
        linea = fila.get("line")
        mercado = traducir_mercado(fila.get("market_key") or "")
        if not mercado or not jugador:
            continue

        mercados = entrada["_books"].setdefault(book, {})
        outcomes = mercados.setdefault(mercado, [])

        for lado, precio in (("Over", fila.get("over_price")),
                             ("Under", fila.get("under_price"))):
            decimal = _a_decimal(precio)
            if decimal:
                outcomes.append({
                    "description": jugador,
                    "name": lado,
                    "point": linea,
                    "price": decimal,
                })

    # Armar la forma final, igual a la de The Odds API.
    salida: dict[str, dict[str, Any]] = {}
    for eid, entrada in por_evento.items():
        salida[eid] = {
            "event": entrada["event"],
            "props": {
                "bookmakers": [
                    {
                        "title": book,
                        "markets": [
                            {"key": k, "outcomes": o} for k, o in mercados.items()
                        ],
                    }
                    for book, mercados in entrada["_books"].items()
                ]
            },
        }
    return salida
