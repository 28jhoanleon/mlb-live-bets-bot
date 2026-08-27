"""Capturar mensajes de un grupo de picks ajeno.

Reglas de Telegram que no se pueden sortear: un bot no puede leer un
grupo del que no forma parte, ni recibir mensajes de otro bot. Las dos
vías que sí funcionan son reenviarle el mensaje a mano, o ponerlo como
administrador de un canal propio donde se publiquen.
"""
import pytest

from app.db import database


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/g.db")
    monkeypatch.setattr(database, "_db_path", lambda: str(tmp_path / "g.db"))
    database.init_db()
    return database


class TestGuardarMensajes:
    def test_guarda_y_lee(self, db):
        db.guardar_mensaje_grupo("Picks MLB", "Juan", "Judge over 1.5 hits")
        mensajes = db.leer_mensajes_grupo()
        assert len(mensajes) == 1
        assert mensajes[0]["texto"] == "Judge over 1.5 hits"
        assert mensajes[0]["autor"] == "Juan"

    def test_no_duplica_el_mismo_mensaje(self, db):
        """Si reenviás dos veces el mismo, no se repite."""
        for _ in range(3):
            db.guardar_mensaje_grupo("Picks MLB", "Juan", "Judge over 1.5")
        assert len(db.leer_mensajes_grupo()) == 1

    def test_el_mas_nuevo_va_primero(self, db):
        db.guardar_mensaje_grupo("G", None, "viejo")
        db.guardar_mensaje_grupo("G", None, "nuevo")
        assert db.leer_mensajes_grupo()[0]["texto"] == "nuevo"

    def test_sin_autor_no_rompe(self, db):
        """Si el autor tiene la privacidad activada, viene anónimo."""
        db.guardar_mensaje_grupo("Canal", None, "un pick")
        assert db.leer_mensajes_grupo()[0]["autor"] is None


class TestHandlerRegistrado:
    def test_escucha_publicaciones_de_canal(self):
        import pathlib

        fuente = pathlib.Path("app/bot/telegram_bot.py").read_text()
        assert "filters.UpdateType.CHANNEL_POST" in fuente

    def test_escucha_reenvios(self):
        import pathlib

        fuente = pathlib.Path("app/bot/telegram_bot.py").read_text()
        assert "filters.FORWARDED" in fuente

    def test_no_contesta_en_canales(self):
        """Responder cada publicación de un canal sería ruido."""
        import pathlib

        fuente = pathlib.Path("app/bot/handlers/grupo.py").read_text()
        assert "if update.channel_post is None:" in fuente


class TestEnLaWeb:
    def test_el_endpoint_existe(self):
        import pathlib

        assert '"/api/mensajes"' in pathlib.Path("app/web/api.py").read_text()

    def test_explica_como_probar_si_esta_vacio(self):
        import pathlib

        html = pathlib.Path("app/web/static/index.html").read_text()
        assert "Reenviale uno al bot" in html
