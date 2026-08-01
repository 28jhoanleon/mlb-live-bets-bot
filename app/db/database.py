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

            CREATE TABLE IF NOT EXISTS legs_resueltas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id TEXT NOT NULL,
                ticket_id TEXT NOT NULL,
                jugador TEXT,
                mercado TEXT,
                linea TEXT,
                prob_estimada REAL,       -- lo que el bot predijo ANTES
                se_dio INTEGER NOT NULL,  -- 1 acertó, 0 no
                registrado_en TEXT NOT NULL,
                UNIQUE (chat_id, ticket_id, jugador, mercado, linea)
            );

            CREATE TABLE IF NOT EXISTS ticket_terminado (
                chat_id TEXT NOT NULL,
                ticket_id TEXT NOT NULL,
                terminado_desde TEXT NOT NULL,
                PRIMARY KEY (chat_id, ticket_id)
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
    """Guarda un resumen legible de lo analizado, para /historial.

    Bug que arregla: buscaba analysis["legs"] y analysis["is_parlay"],
    claves que NO existen -- to_storage() devuelve {"bets": [...]}. Como
    .get() no falla, cada entrada quedaba como "Apuesta simple — ?" sin
    que nada avisara.
    """
    tickets = analysis.get("bets", [])
    legs = [leg for t in tickets for leg in t.get("legs", [])]

    # Resumen: los partidos distintos que toca la apuesta.
    partidos = list(dict.fromkeys(
        leg.get("match") for leg in legs if leg.get("match")
    ))
    if not partidos:
        match_summary = "?"
    elif len(partidos) == 1:
        match_summary = partidos[0]
    else:
        match_summary = f"{partidos[0]} +{len(partidos) - 1}"

    # Es combinada si tiene más de una selección, en uno o varios tickets.
    es_combinada = len(legs) > 1
    with _connection() as conn:
        conn.execute(
            "INSERT INTO bet_history (chat_id, match_summary, is_parlay, analysis_json, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                chat_id,
                match_summary,
                int(es_combinada),
                json.dumps(analysis),
                datetime.now(timezone.utc).isoformat(),
            ),
        )


def get_bet_history(chat_id: int, limit: int = 10) -> list[dict[str, Any]]:
    with _connection() as conn:
        rows = conn.execute(
            "SELECT match_summary, is_parlay, analysis_json, created_at FROM bet_history "
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


# ---------- ticket_terminado (para saber hace cuánto terminó un ticket) ----------
#
# La web recalcula "terminado" en cada pedido a partir del estado en vivo
# de la MLB API — no viene guardado en la apuesta. Para poder aplicar una
# tolerancia ("mostralo un rato más después de terminar, después sacalo
# solo") hace falta acordarse de la primera vez que se vio terminado.

def marcar_terminado_si_hace_falta(chat_id: int, ticket_id: str) -> str:
    """Registra la primera vez que se ve este ticket terminado, y
    devuelve ese momento (ISO). Si ya estaba registrado, no lo pisa —
    la tolerancia se cuenta desde la PRIMERA vez que se vio terminado,
    no desde el último refresco de la página."""
    ahora = datetime.now(timezone.utc).isoformat()
    with _connection() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO ticket_terminado (chat_id, ticket_id, terminado_desde) "
            "VALUES (?, ?, ?)",
            (str(chat_id), ticket_id, ahora),
        )
        row = conn.execute(
            "SELECT terminado_desde FROM ticket_terminado WHERE chat_id = ? AND ticket_id = ?",
            (str(chat_id), ticket_id),
        ).fetchone()
    return row["terminado_desde"]


def olvidar_terminado(chat_id: int, ticket_id: str) -> None:
    """Por si un ticket que se había marcado terminado deja de estarlo
    (dato raro de la API, partido revertido, etc.) — no debería pasar
    en la práctica, pero mejor no dejar basura marcada para siempre."""
    with _connection() as conn:
        conn.execute(
            "DELETE FROM ticket_terminado WHERE chat_id = ? AND ticket_id = ?",
            (str(chat_id), ticket_id),
        )


def prune_tickets_terminados(older_than_hours: int = 48) -> None:
    """Limpia registros viejos para no acumular la tabla al infinito."""
    with _connection() as conn:
        conn.execute(
            "DELETE FROM ticket_terminado WHERE terminado_desde < datetime('now', ?)",
            (f"-{older_than_hours} hours",),
        )


# ---------- legs_resueltas (calibración del modelo) ----------
#
# Se guardan TODAS las legs resueltas, acertadas y falladas, junto con la
# probabilidad que el bot había estimado. Guardar solo las ganadoras
# sería sesgo de supervivencia: no se puede medir si un "70%" es honesto
# mirando únicamente las veces que salió bien.

def registrar_legs_resueltas(chat_id: int, ticket_id: str, legs: list[dict]) -> int:
    """Guarda las legs de un ticket ya resuelto. Idempotente: si el
    ticket ya fue registrado, no duplica (UNIQUE + INSERT OR IGNORE)."""
    ahora = datetime.now(timezone.utc).isoformat()
    filas = [
        (
            str(chat_id), ticket_id,
            l.get("jugador"), l.get("mercado"), l.get("linea"),
            l.get("prob_estimada"), 1 if l.get("se_dio") else 0, ahora,
        )
        for l in legs
    ]
    if not filas:
        return 0
    with _connection() as conn:
        cur = conn.executemany(
            "INSERT OR IGNORE INTO legs_resueltas "
            "(chat_id, ticket_id, jugador, mercado, linea, prob_estimada, se_dio, registrado_en) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            filas,
        )
        return cur.rowcount


def calibracion(chat_id: int) -> list[dict[str, Any]]:
    """Agrupa las legs resueltas en tramos de probabilidad y compara lo
    predicho contra lo que realmente pasó.

    Si el bot dice 70% y en ese tramo acierta el 55%, está inflado."""
    with _connection() as conn:
        filas = conn.execute(
            "SELECT prob_estimada, se_dio FROM legs_resueltas "
            "WHERE chat_id = ? AND prob_estimada IS NOT NULL",
            (str(chat_id),),
        ).fetchall()

    tramos: dict[int, list[int]] = {}
    for f in filas:
        piso = min(int(f["prob_estimada"] // 10 * 10), 90)
        tramos.setdefault(piso, []).append(f["se_dio"])

    salida = []
    for piso in sorted(tramos):
        resultados = tramos[piso]
        salida.append({
            "tramo": f"{piso}-{piso + 9}%",
            "predicho_medio": piso + 5,
            "real_pct": round(sum(resultados) / len(resultados) * 100, 1),
            "muestra": len(resultados),
        })
    return salida


def resumen_calibracion(chat_id: int) -> dict[str, Any]:
    """Totales, para saber si ya hay muestra suficiente."""
    with _connection() as conn:
        fila = conn.execute(
            "SELECT COUNT(*) AS total, SUM(se_dio) AS acertadas, "
            "AVG(prob_estimada) AS prob_media FROM legs_resueltas "
            "WHERE chat_id = ? AND prob_estimada IS NOT NULL",
            (str(chat_id),),
        ).fetchone()
    total = fila["total"] or 0
    return {
        "total": total,
        "acertadas": fila["acertadas"] or 0,
        "real_pct": round((fila["acertadas"] or 0) / total * 100, 1) if total else 0.0,
        "prob_media": round(fila["prob_media"], 1) if fila["prob_media"] else 0.0,
    }


def limpiar_resultados_combos(chat_id: int) -> int:
    """Borra los resultados ya calculados para que se recalculen.

    Hace falta porque los combos resueltos por la versión con bugs
    quedaron con un resultado equivocado guardado, y el código sólo
    resuelve los que están sin resolver: sin limpiarlos, esos combos se
    quedarían mintiendo para siempre.

    No borra los combos: sólo pone `resultado` en NULL."""
    with _connection() as conn:
        cur = conn.execute(
            "UPDATE combos_sugeridos SET resultado = NULL "
            "WHERE chat_id = ? AND resultado IS NOT NULL",
            (chat_id,),
        )
        return cur.rowcount


def limpiar_legs_resueltas(chat_id: int) -> int:
    """Borra las legs guardadas para calibración.

    Las que se registraron mientras el resolutor estaba roto tienen el
    campo `se_dio` equivocado, y una calibración calculada sobre datos
    falsos es peor que no tener calibración."""
    with _connection() as conn:
        cur = conn.execute("DELETE FROM legs_resueltas WHERE chat_id = ?", (str(chat_id),))
        return cur.rowcount
