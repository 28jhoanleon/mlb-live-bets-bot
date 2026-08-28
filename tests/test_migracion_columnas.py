"""Bug real, encontrado en producción: `CREATE TABLE IF NOT EXISTS` no
agrega columnas a una tabla que ya existe.

Quien tenía `mensajes_grupo` o `fuentes` de una versión anterior se
quedó con la tabla vieja, sin `foto` ni `casas`. El primer guardado o
lectura que las mencionara rompía con "no such column" -- el mensaje
"No pude leerlos" que se vio en la web, y también la causa de que las
reacciones no guardaran nada (el error quedaba silenciado dentro del
try/except del lector).
"""
import sqlite3

import pytest

from app.db import database


def _tabla_vieja_sin_columnas_nuevas(ruta: str) -> None:
    """Recrea exactamente el esquema de antes de v107/v108."""
    con = sqlite3.connect(ruta)
    con.executescript("""
        CREATE TABLE mensajes_grupo (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            origen TEXT, autor TEXT, texto TEXT NOT NULL,
            recibido_en TEXT NOT NULL, UNIQUE(origen, texto)
        );
        CREATE TABLE fuentes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL, grupo TEXT NOT NULL UNIQUE,
            autores TEXT, requiere_foto INTEGER DEFAULT 0,
            requiere_link INTEGER DEFAULT 0, palabras TEXT, activa INTEGER DEFAULT 1
        );
    """)
    con.commit()
    con.close()


@pytest.fixture
def db_vieja(tmp_path, monkeypatch):
    ruta = str(tmp_path / "vieja.db")
    _tabla_vieja_sin_columnas_nuevas(ruta)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{ruta}")
    monkeypatch.setattr(database, "_db_path", lambda: ruta)
    return database


class TestMigracionDeUnaBaseVieja:
    def test_init_db_agrega_las_columnas_que_faltan(self, db_vieja):
        db_vieja.init_db()
        with db_vieja._connection() as conn:
            cols_mensajes = {f["name"] for f in conn.execute(
                "PRAGMA table_info(mensajes_grupo)").fetchall()}
            cols_fuentes = {f["name"] for f in conn.execute(
                "PRAGMA table_info(fuentes)").fetchall()}
        assert "foto" in cols_mensajes
        assert "casas" in cols_fuentes

    def test_guardar_con_foto_no_rompe_despues_de_migrar(self, db_vieja):
        db_vieja.init_db()
        db_vieja.guardar_mensaje_grupo("Ludo", "Juan", "pick", foto="/x.jpg")
        assert db_vieja.leer_mensajes_grupo()[0]["foto"] == "/x.jpg"

    def test_agregar_fuente_con_casas_no_rompe_despues_de_migrar(self, db_vieja):
        db_vieja.init_db()
        db_vieja.agregar_fuente("Ludo", "grupo1", casas="stake,bet365")
        assert db_vieja.listar_fuentes()[0]["casas"] == "stake,bet365"

    def test_correr_init_db_dos_veces_no_rompe(self, db_vieja):
        """Se llama en cada arranque; tiene que ser seguro repetirlo."""
        db_vieja.init_db()
        db_vieja.init_db()
        db_vieja.guardar_mensaje_grupo("X", "Y", "z", foto="/a.jpg")
        assert db_vieja.leer_mensajes_grupo()[0]["foto"] == "/a.jpg"

    def test_una_base_nueva_de_cero_tambien_funciona(self, tmp_path, monkeypatch):
        """El caso sin nada previo: CREATE TABLE normal, sin necesidad
        de migrar nada."""
        ruta = str(tmp_path / "nueva.db")
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{ruta}")
        monkeypatch.setattr(database, "_db_path", lambda: ruta)
        database.init_db()
        database.guardar_mensaje_grupo("X", "Y", "z", foto="/a.jpg")
        assert database.leer_mensajes_grupo()[0]["foto"] == "/a.jpg"


class TestObjetivoCalibrado:
    """OBJETIVO_SEGURO (85%) es matemática teórica: asume que cuando el
    modelo dice 85% de verdad acierta 85%. La calibración mide si eso es
    cierto. Se conecta automáticamente, pero solo cuando hay muestra:
    con pocos datos, ajustar sería perseguir ruido."""

    @pytest.fixture
    def db(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/c.db")
        monkeypatch.setattr(database, "_db_path", lambda: str(tmp_path / "c.db"))
        database.init_db()
        return database

    def _cargar_legs(self, db, n, aciertos, prob=85.0):
        with db._connection() as conn:
            for i in range(n):
                conn.execute(
                    "INSERT INTO legs_resueltas (chat_id, ticket_id, jugador, mercado, "
                    "linea, prob_estimada, se_dio, registrado_en) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))",
                    ("1", f"t{i}", f"J{i}", "batter_hits", "Over 0.5", prob,
                     1 if i < aciertos else 0),
                )

    def test_sin_datos_usa_el_teorico(self, db):
        from app.analysis.auditoria import OBJETIVO_SEGURO, objetivo_calibrado

        assert objetivo_calibrado(1) == OBJETIVO_SEGURO

    def test_con_poca_muestra_no_ajusta_todavia(self, db):
        """El caso real de hoy: 15 legs en el bucket, por debajo del
        piso de 20. No hay que tocar nada con esta cantidad."""
        from app.analysis.auditoria import OBJETIVO_SEGURO, objetivo_calibrado

        self._cargar_legs(db, n=15, aciertos=10)  # 66.7%
        assert objetivo_calibrado(1) == OBJETIVO_SEGURO

    def test_con_muestra_suficiente_usa_el_real(self, db):
        from app.analysis.auditoria import objetivo_calibrado

        self._cargar_legs(db, n=20, aciertos=13)  # 65%
        assert objetivo_calibrado(1) == 65.0

    def test_si_el_real_es_mejor_que_el_teorico_tambien_se_usa(self, db):
        """No es solo para corregir sobreconfianza: si el bucket rinde
        MEJOR que el teórico, también vale usarlo."""
        from app.analysis.auditoria import objetivo_calibrado

        self._cargar_legs(db, n=20, aciertos=19)  # 95%
        assert objetivo_calibrado(1) == 95.0

    def test_cada_chat_tiene_su_propia_calibracion(self, db):
        from app.analysis.auditoria import OBJETIVO_SEGURO, objetivo_calibrado

        self._cargar_legs(db, n=20, aciertos=13)
        with db._connection() as conn:
            for i in range(20):
                conn.execute(
                    "INSERT INTO legs_resueltas (chat_id, ticket_id, jugador, mercado, "
                    "linea, prob_estimada, se_dio, registrado_en) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))",
                    ("2", f"z{i}", f"K{i}", "batter_hits", "Over 0.5", 85.0, 1),
                )
        assert objetivo_calibrado(1) == 65.0
        assert objetivo_calibrado(2) == 100.0
