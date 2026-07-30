"""El log del bot listaba los handlers con un texto escrito a mano que
quedó desactualizado: no mencionaba /miid, /sonadora, /combos ni /nueva
aunque los cuatro SÍ estaban registrados. Mirando ese log parecía que
faltaban comandos.

Ahora la lista se deriva del registro real, y este test se asegura de
que ningún comando desaparezca sin que nadie se entere."""
import os

from telegram.ext import CommandHandler, MessageHandler

os.environ.setdefault("BOT_TOKEN", "123:fake")

ESPERADOS = {
    "start", "help", "miid", "games", "today", "live", "props",
    "strikeouts", "hits", "hr", "analyze", "compare", "value",
    "sonadora", "sonadoras", "combos", "refresh", "nueva",
    "historial", "alertas", "noalertas",
}


def _comandos_registrados():
    from app.bot.telegram_bot import build_app

    app = build_app()
    return {
        c
        for h in app.handlers.get(0, [])
        if isinstance(h, CommandHandler)
        for c in h.commands
    }


class TestComandosRegistrados:
    def test_estan_todos_los_comandos_esperados(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/bot.db")
        faltantes = ESPERADOS - _comandos_registrados()
        assert not faltantes, f"comandos que dejaron de estar registrados: {faltantes}"

    def test_las_capturas_siguen_teniendo_handler(self, tmp_path, monkeypatch):
        """Sin este handler el bot deja de leer capturas — que es su
        función principal."""
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/bot.db")
        from app.bot.telegram_bot import build_app

        app = build_app()
        assert any(
            isinstance(h, MessageHandler) for h in app.handlers.get(0, [])
        ), "no hay handler para las fotos: el bot no puede leer capturas"
