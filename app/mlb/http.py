"""Helper HTTP compartido por los submódulos de mlb/ (schedule, live,
players, pitchers). Centraliza timeout, manejo de errores y logging
para no repetir ese boilerplate en cada archivo."""
from __future__ import annotations

from typing import Any

import requests

from app.config import settings
from app.utils.logger import get_logger

log = get_logger(__name__)

TIMEOUT = 10


class MLBClientError(Exception):
    """Error al comunicarse con la MLB Stats API."""


def get(path: str, params: dict[str, Any] | None = None, base_url: str | None = None) -> dict[str, Any]:
    """GET genérico contra la MLB Stats API. `base_url` permite pisar
    la base por defecto (usado por live.py, que vive en /api/v1.1)."""
    url = f"{base_url or settings.mlb_stats_base_url}{path}"
    try:
        resp = requests.get(url, params=params or {}, timeout=TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        log.error("Error llamando a %s: %s", url, exc)
        raise MLBClientError(f"Fallo al consultar MLB Stats API: {exc}") from exc
