"""El log del bot listaba los handlers con un texto escrito a mano que
quedó desactualizado: no mencionaba /miid, /sonadora, /combos ni /nueva
aunque los cuatro SÍ estaban registrados. Mirando ese log parecía que
faltaban comandos.

Ahora la lista se deriva del registro real, y este test se asegura de
que ningún comando desaparezca sin que nadie se entere."""
from telegram.ext import CommandHandler, MessageHandler

ESPERADOS = {
    "start", "help", "miid", "games", "today", "live", "props",
    "strikeouts", "hits", "hr", "analyze", "compare", "value",
    "sonadora", "sonadoras", "combos", "refresh", "nueva",
    "historial", "calibracion", "limpiar", "borrar", "mejorar", "proveedor",
}


def _preparar(tmp_path, monkeypatch):
    """`settings` es un singleton congelado que se construye al importar
    app.config, y para entonces puede no haber BOT_TOKEN todavía. Se
    reemplaza por una copia con token, en el módulo que lo usa."""
    import dataclasses

    from app.bot import telegram_bot
    from app.config import settings

    monkeypatch.setattr(
        telegram_bot, "settings", dataclasses.replace(settings, bot_token="123:fake")
    )
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/bot.db")


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
        _preparar(tmp_path, monkeypatch)
        faltantes = ESPERADOS - _comandos_registrados()
        assert not faltantes, f"comandos que dejaron de estar registrados: {faltantes}"

    def test_las_capturas_siguen_teniendo_handler(self, tmp_path, monkeypatch):
        """Sin este handler el bot deja de leer capturas — que es su
        función principal."""
        _preparar(tmp_path, monkeypatch)
        from app.bot.telegram_bot import build_app

        app = build_app()
        assert any(
            isinstance(h, MessageHandler) for h in app.handlers.get(0, [])
        ), "no hay handler para las fotos: el bot no puede leer capturas"
