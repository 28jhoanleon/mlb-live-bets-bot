"""Administración desde la web, fotos, links clickeables, y el fix de
reacciones en grupos grandes.

Cada sección tiene su propio "por qué":

- Casas: restringir a solo lo que se puede usar desde Argentina.
- Fotos: nunca se capturaban, solo el texto. Hueco real, no un bug de
  borde.
- Links: las capturas que manda la IA muchas veces traen el link
  pegado dentro de números o texto corrido; hacerlo clickeable evita
  copiar y pegar a mano.
- Reacciones: en grupos grandes Telegram manda la actualización
  resumida (solo conteos, sin decir quién reaccionó) -- por eso no
  funcionaba en el grupo de MLB.
"""
import pytest

from app.db import database


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/g.db")
    monkeypatch.setattr(database, "_db_path", lambda: str(tmp_path / "g.db"))
    database.init_db()
    return database


class TestSoloDosCasas:
    def test_pba_stake_pasa(self):
        from app.lector.filtros import tiene_casa

        assert tiene_casa("mirá https://pba.stake.bet.ar/x", "stake")

    def test_stake_com_no_pasa(self):
        """No es usable desde Argentina; no debe contar como match
        aunque el mensaje diga "stake"."""
        from app.lector.filtros import tiene_casa

        assert not tiene_casa("mirá https://stake.com/x", "stake")

    def test_stake_bet_no_pasa(self):
        from app.lector.filtros import tiene_casa

        assert not tiene_casa("mirá https://stake.bet/x", "stake")

    def test_bet365_pasa(self):
        from app.lector.filtros import tiene_casa

        assert tiene_casa("link bet365.com/apuesta", "bet365")

    def test_solo_esas_dos_casas_reconocidas(self):
        """Cualquier otra casa nombrada por su alias no está en la
        tabla; solo pasa si se escribe el dominio exacto."""
        from app.lector.filtros import _CASAS

        assert set(_CASAS) == {"stake", "pba", "bet365"}


class TestFotosSeGuardan:
    def test_guardar_mensaje_con_foto(self, db):
        db.guardar_mensaje_grupo("Ludo", "Juan", "pick del día", foto="/data/fotos_grupo/x.jpg")
        m = db.leer_mensajes_grupo()[0]
        assert m["foto"] == "/data/fotos_grupo/x.jpg"

    def test_mensaje_sin_foto_no_rompe(self, db):
        db.guardar_mensaje_grupo("Ludo", "Juan", "solo texto")
        assert db.leer_mensajes_grupo()[0]["foto"] is None

    def test_la_carpeta_de_fotos_esta_al_lado_de_la_base(self, db):
        """En Railway la base vive en el volumen persistente (/data);
        las fotos tienen que vivir ahí también, o se pierden en el
        próximo deploy."""
        import os

        carpeta = database.carpeta_fotos()
        assert os.path.dirname(database._db_path()) in carpeta or carpeta.startswith(".")


class TestBorrarDesdeLaWeb:
    def test_borrar_un_mensaje(self, db):
        db.guardar_mensaje_grupo("Ludo", "Juan", "pick 1")
        mid = db.leer_mensajes_grupo()[0]["id"]
        assert db.borrar_mensaje_grupo(mid) is True
        assert db.leer_mensajes_grupo() == []

    def test_borrar_lo_inexistente_no_rompe(self, db):
        assert db.borrar_mensaje_grupo(9999) is False

    def test_borrar_los_de_una_fuente(self, db):
        db.guardar_mensaje_grupo("Ludo", "Juan", "pick 1")
        db.guardar_mensaje_grupo("Ludo", "Juan", "pick 2")
        db.guardar_mensaje_grupo("Otro", "Pedro", "pick 3")
        borrados = db.borrar_mensajes_de("Ludo")
        assert borrados == 2
        restantes = db.leer_mensajes_grupo()
        assert len(restantes) == 1
        assert restantes[0]["origen"] == "Otro"

    def test_borrar_un_mensaje_con_foto_borra_el_archivo(self, db, tmp_path):
        archivo = tmp_path / "foto.jpg"
        archivo.write_bytes(b"x")
        db.guardar_mensaje_grupo("Ludo", "Juan", "pick", foto=str(archivo))
        mid = db.leer_mensajes_grupo()[0]["id"]
        db.borrar_mensaje_grupo(mid)
        assert not archivo.exists()


class TestElEndpointDeAdministracion:
    def test_los_endpoints_existen(self):
        import pathlib

        fuente = pathlib.Path("app/web/api.py").read_text()
        assert '"/api/mensajes-accion"' in fuente
        assert '"/api/mensaje-foto"' in fuente

    def test_sin_clave_no_deja_borrar(self):
        """La ruta requiere la clave, igual que el resto de la API."""
        import pathlib

        fuente = pathlib.Path("app/web/api.py").read_text()
        bloque = fuente[fuente.index("async def mensajes_accion"):]
        assert "_clave_ok" in bloque[:300]

    def test_no_hay_rutas_duplicadas(self):
        import pathlib

        fuente = pathlib.Path("app/web/api.py").read_text()
        assert fuente.count('Route("/api/mensajes-accion"') == 1


class TestLinksClickeables:
    def test_la_funcion_enlazar_existe(self):
        import pathlib

        html = pathlib.Path("app/web/static/index.html").read_text()
        assert "function enlazar(" in html

    def test_se_usa_al_mostrar_el_texto(self):
        import pathlib

        html = pathlib.Path("app/web/static/index.html").read_text()
        assert "enlazar(esc(m.texto))" in html

    def test_no_hay_funciones_duplicadas(self):
        """Quedó código de una sesión anterior sin entregar; hay que
        asegurarse de que no se pisó con lo nuevo."""
        import pathlib
        import re

        html = pathlib.Path("app/web/static/index.html").read_text()
        for fn in ("borrarMensaje", "dejarFuente", "filtrarFuente", "cargarMensajes"):
            assert len(re.findall(rf"function {fn}\(", html)) == 1, fn


class TestReaccionesEnGruposGrandes:
    """En grupos grandes Telegram manda la actualización de reacciones
    resumida: solo conteos, sin decir quién reaccionó. `recent_reactions`
    llega vacío justo ahí. Por eso no andaba en el grupo de MLB."""

    def test_pide_la_lista_completa_si_no_vino_resumida(self):
        import pathlib

        fuente = pathlib.Path("app/lector/cliente.py").read_text()
        assert "GetMessageReactionsListRequest" in fuente

    def test_hay_una_funcion_dedicada_a_resolver_mi_reaccion(self):
        import pathlib

        fuente = pathlib.Path("app/lector/cliente.py").read_text()
        assert "async def _mi_reaccion(" in fuente


class TestBorrarTodosLosMensajes:
    def test_borra_todo(self, db):
        db.guardar_mensaje_grupo("A", "x", "pick 1")
        db.guardar_mensaje_grupo("B", "y", "pick 2")
        assert db.borrar_todos_los_mensajes() == 2
        assert db.leer_mensajes_grupo() == []

    def test_no_toca_las_fuentes(self, db):
        db.agregar_fuente("A", "grupo_a")
        db.guardar_mensaje_grupo("A", "x", "pick 1")
        db.borrar_todos_los_mensajes()
        assert len(db.listar_fuentes()) == 1

    def test_borra_las_fotos_del_disco(self, db, tmp_path):
        archivo = tmp_path / "f.jpg"
        archivo.write_bytes(b"x")
        db.guardar_mensaje_grupo("A", "x", "pick", foto=str(archivo))
        db.borrar_todos_los_mensajes()
        assert not archivo.exists()

    def test_con_la_base_vacia_no_rompe(self, db):
        assert db.borrar_todos_los_mensajes() == 0


class TestEndpointBorrarTodos:
    def test_existe_la_accion_todos(self):
        import pathlib

        fuente = pathlib.Path("app/web/api.py").read_text()
        assert 'accion == "todos"' in fuente
