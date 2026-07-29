"""Persistencia en SQLite. Reemplaza el estado en memoria (que se
perdía en cada reinicio) por algo que sobrevive.

Tablas:
  active_bets       -> última combinada/apuesta por chat, para /refresh
  bet_history       -> historial de todo lo analizado (para auditar
                        después qué picks funcionaron)
  alert_subscribers -> chats suscriptos a alertas automáticas de +EV
  seen_value_alerts -> dedup para no mandar la misma alerta 2 veces

DATABASE_URL soporta 'sqlite:///archivo.db' — parseamos el path de ahí.
Si algún día se migra a Postgres, esta es la capa que hay que
reemplazar (el resto de la app no toca SQL directamente).
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from app.config import settings
from app.utils.logger import get_logger

log = get_logger(__name__)


def _db_path() -> str:
    url = settings.database_url
    if url.startswith("sqlite:///"):
        return url.removeprefix("sqlite:///")
    log.warning("DATABASE_URL '%s' no es sqlite — usando mlb_bets.db local por defecto.", url)
    return "mlb_bets.db"


@contextmanager
def _connection() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    """Crea las tablas si no existen. Se llama una vez al arrancar el bot."""
    with _connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS active_bets (
                chat_id INTEGER PRIMARY KEY,
                analysis_json TEXT NOT NULL,
                saved_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS bet_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                match_summary TEXT,
                is_parlay INTEGER,
                analysis_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS alert_subscribers (
                chat_id INTEGER PRIMARY KEY,
                subscribed_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS combos_sugeridos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                tipo TEXT NOT NULL,            -- 'value' o 'sonadora'
                legs_json TEXT NOT NULL,
                cuota REAL,
                probabilidad REAL,
                creado_en TEXT NOT NULL,
                resultado TEXT               -- NULL = sin resolver
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS seen_value_alerts (
                alert_key TEXT PRIMARY KEY,
                seen_at TEXT NOT NULL
            );
            """
        )
    log.info("Base de datos inicializada en %s", _db_path())


# ---------- active_bets (para /refresh) ----------

def save_active_bet(chat_id: int, analysis: dict[str, Any]) -> None:
    with _connection() as conn:
        conn.execute(
            "INSERT INTO active_bets (chat_id, analysis_json, saved_at) VALUES (?, ?, ?) "
            "ON CONFLICT(chat_id) DO UPDATE SET analysis_json=excluded.analysis_json, saved_at=excluded.saved_at",
            (chat_id, json.dumps(analysis), datetime.now(timezone.utc).isoformat()),
        )


def get_active_bet(chat_id: int) -> dict[str, Any] | None:
    with _connection() as conn:
        row = conn.execute(
            "SELECT analysis_json FROM active_bets WHERE chat_id = ?", (chat_id,)
        ).fetchone()
    return json.loads(row["analysis_json"]) if row else None


# ---------- bet_history ----------

def log_bet_analysis(chat_id: int, analysis: dict[str, Any]) -> None:
    legs = analysis.get("legs", [])
    match_summary = legs[0].get("match", "?") if legs else "?"
    with _connection() as conn:
        conn.execute(
            "INSERT INTO bet_history (chat_id, match_summary, is_parlay, analysis_json, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                chat_id,
                match_summary,
                int(bool(analysis.get("is_parlay"))),
                json.dumps(analysis),
                datetime.now(timezone.utc).isoformat(),
            ),
        )


def get_bet_history(chat_id: int, limit: int = 10) -> list[dict[str, Any]]:
    with _connection() as conn:
        rows = conn.execute(
            "SELECT match_summary, is_parlay, created_at FROM bet_history "
            "WHERE chat_id = ? ORDER BY id DESC LIMIT ?",
            (chat_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


# ---------- alert_subscribers ----------

def subscribe_alerts(chat_id: int) -> None:
    with _connection() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO alert_subscribers (chat_id, subscribed_at) VALUES (?, ?)",
            (chat_id, datetime.now(timezone.utc).isoformat()),
        )


def unsubscribe_alerts(chat_id: int) -> None:
    with _connection() as conn:
        conn.execute("DELETE FROM alert_subscribers WHERE chat_id = ?", (chat_id,))


def is_subscribed(chat_id: int) -> bool:
    with _connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM alert_subscribers WHERE chat_id = ?", (chat_id,)
        ).fetchone()
    return row is not None


def get_subscribed_chats() -> list[int]:
    with _connection() as conn:
        rows = conn.execute("SELECT chat_id FROM alert_subscribers").fetchall()
    return [r["chat_id"] for r in rows]


# ---------- seen_value_alerts (dedup) ----------

def has_seen_alert(alert_key: str) -> bool:
    with _connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM seen_value_alerts WHERE alert_key = ?", (alert_key,)
        ).fetchone()
    return row is not None


def mark_alert_seen(alert_key: str) -> None:
    with _connection() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO seen_value_alerts (alert_key, seen_at) VALUES (?, ?)",
            (alert_key, datetime.now(timezone.utc).isoformat()),
        )


def prune_old_alerts(older_than_hours: int = 12) -> None:
    """Limpia alertas vistas hace rato, para no acumular la tabla al
    infinito (los partidos de un día ya no importan al día siguiente)."""
    with _connection() as conn:
        conn.execute(
            "DELETE FROM seen_value_alerts WHERE seen_at < datetime('now', ?)",
            (f"-{older_than_hours} hours",),
        )


def clear_active_bet(chat_id: int) -> None:
    """Borra la apuesta activa de un chat.

    Las capturas se acumulan por defecto, así que sin esto las apuestas
    viejas seguirían apareciendo en cada análisis nuevo.
    """
    with _connection() as conn:
        conn.execute("DELETE FROM active_bets WHERE chat_id = ?", (chat_id,))


def guardar_combo_sugerido(
    chat_id: int, tipo: str, legs: list[dict], cuota: float, probabilidad: float
) -> int:
    """Guarda una combinada sugerida para poder revisarla después.

    Se guarda aunque el usuario no la juegue: la idea es poder mirar en
    retrospectiva si las sugerencias se daban o no.
    """
    with _connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO combos_sugeridos
                (chat_id, tipo, legs_json, cuota, probabilidad, creado_en)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                chat_id,
                tipo,
                json.dumps(legs, ensure_ascii=False),
                cuota,
                probabilidad,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        return cur.lastrowid


def listar_combos_sugeridos(chat_id: int, limite: int = 10) -> list[dict]:
    with _connection() as conn:
        filas = conn.execute(
            """
            SELECT id, tipo, legs_json, cuota, probabilidad, creado_en, resultado
            FROM combos_sugeridos
            WHERE chat_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (chat_id, limite),
        ).fetchall()

    return [
        {
            "id": f[0],
            "tipo": f[1],
            "legs": json.loads(f[2]),
            "cuota": f[3],
            "probabilidad": f[4],
            "creado_en": f[5],
            "resultado": f[6],
        }
        for f in filas
    ]


def marcar_resultado_combo(combo_id: int, resultado: str) -> None:
    with _connection() as conn:
        conn.execute(
            "UPDATE combos_sugeridos SET resultado = ? WHERE id = ?",
            (resultado, combo_id),
        )
