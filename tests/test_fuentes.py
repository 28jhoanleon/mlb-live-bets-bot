"""Seguir varios grupos, cada uno con sus propios filtros.

De un grupo puede interesarte todo; de otro, solo lo que publica cierta
persona, o solo los mensajes con foto o con link. Sin filtros, seguir
varios convierte la pestaña en un chat entero y deja de servir.
"""
import pytest

from app.db import database
from app.lector.filtros import autor_permitido, pasa, tiene_link, tiene_palabra


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/f.db")
    monkeypatch.setattr(database, "_db_path", lambda: str(tmp_path / "f.db"))
    database.init_db()
    return database


class TestFiltroPorAutor:
    def test_sin_lista_pasa_cualquiera(self):
        assert autor_permitido("Quien sea", "")

    def test_con_lista_solo_esos(self):
        assert autor_permitido("Ludo", "Ludo,Juan")
        assert not autor_permitido("Pedro", "Ludo,Juan")

    def test_coincidencia_parcial(self):
        """En Telegram el nombre viene con apellido o emojis; pedir
        igualdad exacta fallaría casi siempre."""
        assert autor_permitido("Ludo Gallina", "Ludo")

    def test_sin_autor_con_lista_no_pasa(self):
        assert not autor_permitido(None, "Ludo")


class TestOtrosFiltros:
    def test_link(self):
        assert tiene_link("mirá https://stake.bet.ar/x")
        assert tiene_link("t.me/algo")
        assert not tiene_link("sin enlaces acá")

    def test_palabras(self):
        assert tiene_palabra("MLB hoy", "mlb,nba")
        assert not tiene_palabra("futbol hoy", "mlb,nba")

    def test_sin_palabras_pasa_todo(self):
        assert tiene_palabra("cualquier cosa", "")


class TestCombinado:
    def _fuente(self, **kw):
        base = {"autores": "", "requiere_foto": 0, "requiere_link": 0, "palabras": ""}
        base.update(kw)
        return base

    def test_el_caso_completo(self):
        f = self._fuente(autores="Ludo", palabras="mlb,over")
        assert pasa(f, "MLB Judge over 1.5", "Ludo", False)
        assert not pasa(f, "MLB Judge over 1.5", "Otro", False)
        assert not pasa(f, "hola gente", "Ludo", False)

    def test_requiere_foto(self):
        f = self._fuente(requiere_foto=1)
        assert pasa(f, "un pick", "X", True)
        assert not pasa(f, "un pick", "X", False)

    def test_requiere_link(self):
        f = self._fuente(requiere_link=1)
        assert pasa(f, "mirá https://x.com", "X", False)
        assert not pasa(f, "sin link", "X", False)

    def test_sin_filtros_pasa_todo(self):
        assert pasa(self._fuente(), "lo que sea", None, False)


class TestGuardarFuentes:
    def test_agregar_y_listar(self, db):
        db.agregar_fuente("Ludo MLB", "ludogallina2024", "Ludo", palabras="mlb")
        fuentes = db.listar_fuentes()
        assert len(fuentes) == 1
        assert fuentes[0]["nombre"] == "Ludo MLB"
        assert fuentes[0]["autores"] == "Ludo"

    def test_agregar_dos_veces_actualiza(self, db):
        db.agregar_fuente("Viejo", "grupo1")
        db.agregar_fuente("Nuevo", "grupo1", autores="Juan")
        fuentes = db.listar_fuentes()
        assert len(fuentes) == 1
        assert fuentes[0]["nombre"] == "Nuevo"

    def test_saca_la_arroba(self, db):
        db.agregar_fuente("X", "@ludogallina2024")
        assert db.listar_fuentes()[0]["grupo"] == "ludogallina2024"

    def test_borrar(self, db):
        db.agregar_fuente("X", "grupo1")
        assert db.borrar_fuente("grupo1") is True
        assert db.listar_fuentes() == []

    def test_borrar_lo_inexistente(self, db):
        assert db.borrar_fuente("no-existe") is False


class TestElLectorUsaLasFuentes:
    def test_descarta_los_chats_no_configurados(self):
        """La sesión ve TODOS los chats: si no está en la lista, ni se
        toca."""
        import types

        from app.lector.cliente import _fuente_de

        fuentes = [{"grupo": "ludogallina2024", "nombre": "Ludo"}]
        ajeno = types.SimpleNamespace(username="chat_privado", id=123)
        assert _fuente_de(ajeno, fuentes) is None

    def test_encuentra_la_fuente_correcta(self):
        import types

        from app.lector.cliente import _fuente_de

        fuentes = [
            {"grupo": "grupo_a", "nombre": "A"},
            {"grupo": "grupo_b", "nombre": "B"},
        ]
        chat = types.SimpleNamespace(username="grupo_b", id=1)
        assert _fuente_de(chat, fuentes)["nombre"] == "B"


class TestFiltroPorCasaDeApuestas:
    """Quedarse solo con los picks que traen el cupón para copiar, y
    descartar los comentarios sueltos."""

    def test_reconoce_el_stake_argentino(self):
        from app.lector.filtros import tiene_casa

        assert tiene_casa("mirá https://pba.stake.bet.ar/sports/x", "stake")

    def test_reconoce_bet365(self):
        from app.lector.filtros import tiene_casa

        assert tiene_casa("link de bet365.com/apuesta", "bet365")

    def test_descarta_otras_casas(self):
        """Si pediste solo stake y bet365, betano no pasa."""
        from app.lector.filtros import tiene_casa

        assert not tiene_casa("https://betano.bet.ar/x", "stake,bet365")

    def test_descarta_texto_sin_link(self):
        from app.lector.filtros import tiene_casa

        assert not tiene_casa("hoy va a estar bueno el partido", "stake")

    def test_sin_casas_pedidas_pasa_todo(self):
        from app.lector.filtros import tiene_casa

        assert tiene_casa("cualquier cosa", "")

    def test_acepta_un_dominio_escrito_a_mano(self):
        """Si nombrás una casa que no está en la tabla, se busca tal cual."""
        from app.lector.filtros import tiene_casa

        assert tiene_casa("https://casarara.com/x", "casarara.com")

    def test_se_guarda_en_la_fuente(self, db):
        db.agregar_fuente("Ludo", "grupo1", casas="stake,bet365")
        assert db.listar_fuentes()[0]["casas"] == "stake,bet365"


class TestCapturaPorReaccion:
    """Reaccionar con un emoji guarda ese mensaje aunque no cumpla
    ningún filtro: es curación manual sin escribir nada."""

    def test_hay_emojis_por_defecto(self):
        from app.lector.cliente import _emojis_configurados

        assert _emojis_configurados()

    def test_solo_cuentan_las_reacciones_propias(self):
        """Que otro reaccione no debe guardar nada."""
        import pathlib

        fuente = pathlib.Path("app/lector/cliente.py").read_text()
        assert "yo_id" in fuente
        assert "user_id\", None) == yo_id" in fuente

    def test_una_reaccion_distinta_no_guarda(self):
        from app.lector.cliente import _emojis_configurados

        assert "💩" not in _emojis_configurados()

    def test_funciona_aunque_el_chat_no_sea_fuente(self):
        """Si marcás algo de otro grupo, se guarda igual: fuiste vos
        quien lo eligió explícitamente."""
        import pathlib

        fuente = pathlib.Path("app/lector/cliente.py").read_text()
        assert 'origen = fuente["nombre"] if fuente else "marcado con reacción"' in fuente
