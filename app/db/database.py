"""Persistencia en SQLite. Reemplaza el estado en memoria (que se
perdía en cada reinicio) por algo que sobrevive.

Tablas:
  active_bets       -> última combinada/apuesta por chat, para /refresh
  bet_history       -> historial de todo lo analizado (para auditar
                        después qué picks funcionaron)
  alert_subscribers -> chats suscriptos a alertas automáticas de +EV

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


def carpeta_fotos() -> str:
    """Al lado de la base, para que viva en el mismo volumen persistente
    (en Railway, /data) y no se pierda en cada deploy."""
    import os

    carpeta = os.path.join(os.path.dirname(_db_path()) or ".", "fotos_grupo")
    os.makedirs(carpeta, exist_ok=True)
    return carpeta


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

            CREATE TABLE IF NOT EXISTS fuentes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL,
                grupo TEXT NOT NULL UNIQUE,
                autores TEXT,          -- lista separada por comas; vacío = todos
                requiere_foto INTEGER DEFAULT 0,
                requiere_link INTEGER DEFAULT 0,
                palabras TEXT,         -- alguna de estas debe aparecer; vacío = cualquiera
                casas TEXT,            -- solo links de estas casas; vacío = cualquier link
                activa INTEGER DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS mensajes_grupo (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                origen TEXT,
                autor TEXT,
                texto TEXT NOT NULL,
                foto TEXT,             -- ruta del archivo, si vino con imagen
                recibido_en TEXT NOT NULL,
                UNIQUE (origen, texto)
            );

            CREATE TABLE IF NOT EXISTS ajustes (
                clave TEXT PRIMARY KEY,
                valor TEXT
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
    _migrar_columnas_nuevas()
    log.info("Base de datos inicializada en %s", _db_path())


def _migrar_columnas_nuevas() -> None:
    """Agrega columnas nuevas a tablas que ya existían.

    `CREATE TABLE IF NOT EXISTS` no toca una tabla que ya existe: si
    alguien tenía `mensajes_grupo` o `fuentes` de una versión anterior,
    las columnas agregadas después (foto, casas) nunca se sumaban. La
    tabla quedaba desactualizada en silencio, y el primer INSERT o
    SELECT que las mencionara rompía con "no such column" -- que es
    justo el error "No pude leerlos" que se vio en la web.
    """
    columnas_por_tabla = {
        "mensajes_grupo": [("foto", "TEXT")],
        "fuentes": [
            ("casas", "TEXT"),
            ("solo_apuestas", "INTEGER DEFAULT 0"),
            ("autor_ids", "TEXT"),  # IDs de Telegram, no nombres -- ver nota abajo
        ],
    }
    with _connection() as conn:
        for tabla, columnas in columnas_por_tabla.items():
            existentes = {
                fila["name"]
                for fila in conn.execute(f"PRAGMA table_info({tabla})").fetchall()
            }
            for columna, tipo in columnas:
                if columna not in existentes:
                    conn.execute(f"ALTER TABLE {tabla} ADD COLUMN {columna} {tipo}")
                    log.info("Migración: agregada columna %s.%s", tabla, columna)


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


def borrar_ticket(chat_id: int, indice: int) -> str | None:
    """Borra UN ticket de la apuesta activa, por su posición (1-based).

    Complementa a /nueva, que borra todo. Devuelve una descripción del
    ticket borrado, o None si el índice no existe."""
    actual = get_active_bet(chat_id)
    if not actual:
        return None

    tickets = actual.get("bets", [])
    if indice < 1 or indice > len(tickets):
        return None

    borrado = tickets.pop(indice - 1)
    legs = borrado.get("legs", [])
    partido = legs[0].get("match", "?") if legs else "?"
    descripcion = f"{partido} · {len(legs)} tramo(s)"

    if tickets:
        actual["bets"] = tickets
        save_active_bet(chat_id, actual)
    else:
        clear_active_bet(chat_id)
    return descripcion


def chats_con_apuesta_activa() -> list[int]:
    """Chats que tienen una apuesta guardada.

    Lo usa el job que registra legs resueltas para calibración, que
    necesita recorrerlos sin depender de que alguien abra la web."""
    with _connection() as conn:
        filas = conn.execute("SELECT DISTINCT chat_id FROM active_bets").fetchall()
    return [f["chat_id"] for f in filas]


def _tickets_de(chat_id: int) -> tuple[dict | None, list[dict]]:
    actual = get_active_bet(chat_id)
    return actual, (actual or {}).get("bets", [])


def confirmar_borrador(chat_id: int, ticket_id: str, calcular_id) -> bool:
    """Un borrador pasa a ser apuesta de verdad: se le saca la marca.

    `calcular_id` se recibe como parámetro para no importar la capa web
    desde la base (evita un ciclo de imports)."""
    from app.analysis.tickets import normalize

    actual, _ = _tickets_de(chat_id)
    if not actual:
        return False

    # Misma razón que en descartar_ticket: los ids que ve el usuario se
    # calculan sobre la vista normalizada.
    vista = normalize(actual)
    encontrado = False
    for t in vista:
        if calcular_id(t, t.get("legs", [])) == ticket_id and t.get("borrador"):
            t.pop("borrador", None)
            encontrado = True

    if encontrado:
        save_active_bet(chat_id, {**actual, "bets": vista})
    return encontrado


def descartar_ticket(chat_id: int, ticket_id: str, calcular_id) -> bool:
    """Saca un ticket concreto de la apuesta activa, por su id.

    Ojo con esto: la web NO muestra los tickets tal como están guardados.
    Antes de mostrarlos pasan por normalize(), que puede partir uno en
    varios (uno por partido). Así que los ids que ve el usuario se
    calculan sobre la versión normalizada y no existen en la guardada.
    Buscar solo en lo guardado hacía que el botón × no encontrara nada.

    Por eso se compara contra la MISMA vista que ve el usuario, y se
    reescribe la apuesta con lo que quedó.
    """
    from app.analysis.tickets import normalize

    actual, _ = _tickets_de(chat_id)
    if not actual:
        return False

    vista = normalize(actual)
    quedan = [t for t in vista if calcular_id(t, t.get("legs", [])) != ticket_id]
    if len(quedan) == len(vista):
        return False  # ese id no está en pantalla

    if quedan:
        save_active_bet(chat_id, {**actual, "bets": quedan})
    else:
        clear_active_bet(chat_id)
    return True


def guardar_cuota(proveedor: str, restante: int) -> None:
    """Última cuota conocida de una API de cuotas.

    Se persiste porque el valor solo se conoce después de consultar, y
    tras un reinicio de Railway se perdía: la web no podía mostrar nada
    hasta que alguien pidiera soñadoras."""
    with _connection() as conn:
        conn.execute(
            "INSERT INTO ajustes (clave, valor) VALUES (?, ?) "
            "ON CONFLICT(clave) DO UPDATE SET valor = excluded.valor",
            (f"cuota_{proveedor}", str(restante)),
        )


def leer_cuotas() -> dict[str, int]:
    with _connection() as conn:
        filas = conn.execute(
            "SELECT clave, valor FROM ajustes WHERE clave LIKE 'cuota_%'"
        ).fetchall()
    salida = {}
    for f in filas:
        try:
            salida[f["clave"].removeprefix("cuota_")] = int(f["valor"])
        except (TypeError, ValueError):
            continue
    return salida


def fijar_cuota_ticket(chat_id: int, ticket_id: str, cuota: str, calcular_id) -> bool:
    """Corrige a mano la cuota total de una apuesta.

    Hace falta porque la IA no siempre encuentra la cuota en la captura
    (algunos cupones no la muestran, o queda cortada). Sin esto la
    apuesta quedaba para siempre como "Sin cuota leída" y no se podía
    calcular cuánto paga."""
    from app.analysis.tickets import normalize

    actual = get_active_bet(chat_id)
    if not actual:
        return False

    vista = normalize(actual)
    encontrado = False
    for t in vista:
        if calcular_id(t, t.get("legs", [])) == ticket_id:
            t["total_odds"] = cuota
            encontrado = True

    if encontrado:
        save_active_bet(chat_id, {**actual, "bets": vista})
    return encontrado


def guardar_mensaje_grupo(
    origen: str, autor: str | None, texto: str, foto: str | None = None,
) -> None:
    """Guarda un mensaje llegado desde un grupo o canal de picks.

    `foto`, si viene, es la ruta al archivo ya descargado (ver
    app.lector.cliente) — acá solo se persiste la ruta.
    """
    with _connection() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO mensajes_grupo (origen, autor, texto, foto, "
            "recibido_en) VALUES (?, ?, ?, ?, ?)",
            (origen, autor, texto, foto, datetime.now(timezone.utc).isoformat()),
        )


def leer_mensajes_grupo(limite: int = 50) -> list[dict[str, Any]]:
    with _connection() as conn:
        filas = conn.execute(
            "SELECT id, origen, autor, texto, foto, recibido_en FROM mensajes_grupo "
            "ORDER BY id DESC LIMIT ?",
            (limite,),
        ).fetchall()
    return [dict(f) for f in filas]


# ---------- fuentes de picks ----------
#
# Cada fuente es un grupo de Telegram con sus propios filtros. Sirve
# para seguir varios a la vez con criterios distintos: de uno querés
# todo, de otro solo lo que publica cierta persona con foto.

def agregar_fuente(
    nombre: str, grupo: str, autores: str = "", requiere_foto: bool = False,
    requiere_link: bool = False, palabras: str = "", casas: str = "",
    solo_apuestas: bool = False, autor_ids: str = "",
) -> None:
    with _connection() as conn:
        conn.execute(
            "INSERT INTO fuentes (nombre, grupo, autores, requiere_foto, "
            "requiere_link, palabras, casas, solo_apuestas, autor_ids) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(grupo) DO UPDATE SET nombre=excluded.nombre, "
            "autores=excluded.autores, requiere_foto=excluded.requiere_foto, "
            "requiere_link=excluded.requiere_link, palabras=excluded.palabras, "
            "casas=excluded.casas, solo_apuestas=excluded.solo_apuestas, "
            "autor_ids=excluded.autor_ids, activa=1",
            (nombre, grupo.strip().lstrip("@"), autores, int(requiere_foto),
             int(requiere_link), palabras, casas, int(solo_apuestas), autor_ids),
        )


def agregar_autor_a_fuente(grupo: str, autor: str, autor_id: int | None = None) -> None:
    """Suma un autor (nombre Y, si se tiene, id numérico) a una fuente ya
    seguida, sin duplicar ni pisar los que ya estaban.

    El id es lo que de verdad distingue a una persona -- el nombre es
    solo para mostrarlo en el panel. Comparar por nombre es ambiguo: en
    un grupo de miles de personas, alguien que se llama "C" o "Le" es
    una subcadena de "Cara Roja" o "leandro", así que un filtro por
    texto lo dejaría pasar sin querer. El id de Telegram no tiene ese
    problema: es único por persona.
    """
    grupo = grupo.strip().lstrip("@")
    with _connection() as conn:
        fila = conn.execute(
            "SELECT autores, autor_ids FROM fuentes WHERE grupo = ?", (grupo,)
        ).fetchone()
        if fila is None:
            return

        actuales = [a.strip() for a in (fila["autores"] or "").split(",") if a.strip()]
        if autor and autor.lower() not in (a.lower() for a in actuales):
            actuales.append(autor)

        ids_actuales = [i.strip() for i in (fila["autor_ids"] or "").split(",") if i.strip()]
        if autor_id is not None and str(autor_id) not in ids_actuales:
            ids_actuales.append(str(autor_id))

        conn.execute(
            "UPDATE fuentes SET autores = ?, autor_ids = ? WHERE grupo = ?",
            (",".join(actuales), ",".join(ids_actuales), grupo),
        )


def listar_fuentes(solo_activas: bool = True) -> list[dict[str, Any]]:
    consulta = "SELECT * FROM fuentes"
    if solo_activas:
        consulta += " WHERE activa = 1"
    with _connection() as conn:
        return [dict(f) for f in conn.execute(consulta + " ORDER BY id").fetchall()]


def borrar_fuente(grupo: str) -> bool:
    with _connection() as conn:
        cur = conn.execute(
            "DELETE FROM fuentes WHERE grupo = ?", (grupo.strip().lstrip("@"),)
        )
        return cur.rowcount > 0


def borrar_mensaje_grupo(mensaje_id: int) -> bool:
    """Borra un mensaje puntual, y su foto en disco si tenía."""
    with _connection() as conn:
        fila = conn.execute(
            "SELECT foto FROM mensajes_grupo WHERE id = ?", (mensaje_id,)
        ).fetchone()
        if fila is None:
            return False
        conn.execute("DELETE FROM mensajes_grupo WHERE id = ?", (mensaje_id,))

    if fila["foto"]:
        _borrar_archivo(fila["foto"])
    return True


def borrar_mensajes_de(origen: str) -> int:
    """Borra todo lo guardado de una fuente, fotos incluidas. Devuelve
    cuántos mensajes sacó."""
    with _connection() as conn:
        fotos = [
            f["foto"] for f in conn.execute(
                "SELECT foto FROM mensajes_grupo WHERE origen = ? AND foto IS NOT NULL",
                (origen,),
            ).fetchall()
        ]
        cur = conn.execute("DELETE FROM mensajes_grupo WHERE origen = ?", (origen,))

    for foto in fotos:
        _borrar_archivo(foto)
    return cur.rowcount


def _borrar_archivo(ruta: str) -> None:
    import os

    try:
        os.remove(ruta)
    except OSError:
        pass
