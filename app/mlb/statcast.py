"""Datos de Statcast (Baseball Savant): xBA, xSLG y compañía.

Por qué sirve: el promedio de bateo dice lo que PASÓ; las métricas
esperadas dicen lo que el bateador está *generando*. Un tipo con .180
de average pero mucho contacto duro está bateando mejor de lo que
muestra su número, y el mercado suele tardar en corregir eso.

Por qué este endpoint y no scrapear la página: Savant expone las
leaderboards como CSV (`csv=true`). Es lo que usa el paquete `baseballr`
de R desde hace años, así que es razonablemente estable. Se parsea con
el módulo `csv` de la stdlib: sin dependencias nuevas y sin nada que
compile — importante porque el desarrollo es desde Termux en Android.

Alcance real (para no sobrevenderlo): esto es por TEMPORADA, no por
partido. Sirve para comparar jugadores y elegir picks; no aporta nada
al seguimiento en vivo.
"""
from __future__ import annotations

import csv
import io
from datetime import date
from typing import Any

import requests

from app.utils.logger import get_logger

log = get_logger(__name__)

_BASE = "https://baseballsavant.mlb.com/leaderboard/expected_statistics"
_TIMEOUT = 20

# El leaderboard cambia una vez por día como mucho: cachear por fecha
# evita bajar el mismo CSV de ~500 filas en cada consulta.
_cache: dict[tuple[str, int], dict[str, dict[str, Any]]] = {}
_cache_fecha: date | None = None


class StatcastError(RuntimeError):
    pass


def _a_float(valor: str) -> float | None:
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def _descargar(tipo: str, anio: int) -> str:
    params = {
        "type": tipo,          # "batter" o "pitcher"
        "year": str(anio),
        "position": "",
        "team": "",
        "min": "q",            # solo los que califican
        "csv": "true",
    }
    try:
        resp = requests.get(_BASE, params=params, timeout=_TIMEOUT)
        resp.raise_for_status()
        return resp.text
    except requests.RequestException as exc:
        raise StatcastError(f"No pude bajar el CSV de Savant: {exc}") from exc


def get_expected_stats(tipo: str = "batter", anio: int | None = None) -> dict[str, dict[str, Any]]:
    """Devuelve {nombre_normalizado: {...métricas...}} para la temporada.

    El CSV trae el nombre como "Apellido, Nombre"; se normaliza a
    "nombre apellido" en minúsculas para poder cruzarlo con lo que leemos
    de las capturas.
    """
    global _cache_fecha
    anio = anio or date.today().year

    hoy = date.today()
    if _cache_fecha != hoy:
        _cache.clear()
        _cache_fecha = hoy

    clave = (tipo, anio)
    if clave in _cache:
        return _cache[clave]

    crudo = _descargar(tipo, anio)
    salida: dict[str, dict[str, Any]] = {}
    for fila in csv.DictReader(io.StringIO(crudo)):
        crudo_nombre = (fila.get("last_name, first_name") or "").strip()
        if not crudo_nombre:
            continue
        if "," in crudo_nombre:
            apellido, nombre = [p.strip() for p in crudo_nombre.split(",", 1)]
            legible = f"{nombre} {apellido}"
        else:
            legible = crudo_nombre

        salida[legible.lower()] = {
            "nombre": legible,
            "player_id": fila.get("player_id"),
            "pa": _a_float(fila.get("pa", "")),
            "ba": _a_float(fila.get("ba", "")),
            "xba": _a_float(fila.get("est_ba", "")),
            "slg": _a_float(fila.get("slg", "")),
            "xslg": _a_float(fila.get("est_slg", "")),
            "woba": _a_float(fila.get("woba", "")),
            "xwoba": _a_float(fila.get("est_woba", "")),
        }

    if not salida:
        raise StatcastError("El CSV de Savant vino vacío o con otro formato")

    _cache[clave] = salida
    log.info("Statcast %s %s: %d jugadores", tipo, anio, len(salida))
    return salida


def buscar_jugador(nombre: str, tipo: str = "batter", anio: int | None = None) -> dict[str, Any] | None:
    """Busca a un jugador por nombre. Tolera diferencias de acentos y
    nombres parciales, igual que el resto del proyecto."""
    from difflib import SequenceMatcher

    from app.analysis.probability import _normalize

    try:
        tabla = get_expected_stats(tipo, anio)
    except StatcastError:
        log.warning("Statcast no disponible", exc_info=True)
        return None

    buscado = _normalize(nombre)
    if buscado in tabla:
        return tabla[buscado]

    mejor, ratio_mejor = None, 0.0
    for clave, datos in tabla.items():
        ratio = SequenceMatcher(None, buscado, _normalize(clave)).ratio()
        if ratio > ratio_mejor:
            mejor, ratio_mejor = datos, ratio
    return mejor if ratio_mejor >= 0.88 else None


def diferencia_xba(datos: dict[str, Any]) -> float | None:
    """xBA - BA. Positivo = está bateando mejor de lo que dice su
    promedio (mala suerte hasta ahora). Negativo = viene con suerte."""
    if not datos or datos.get("xba") is None or datos.get("ba") is None:
        return None
    return round(datos["xba"] - datos["ba"], 3)
