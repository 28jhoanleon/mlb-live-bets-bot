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
