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
        """Si marcás algo de un grupo que todavía no seguís, ahora SÍ
        empieza a seguirse: reaccionar es la forma de decir "seguí a
        esta persona de acá en más"."""
        import pathlib

        fuente = pathlib.Path("app/lector/cliente.py").read_text()
        assert "agregar_fuente, nombre, handle, autor" in fuente


class TestSoloApuestas:
    """Reaccionar a alguien crea o extiende una fuente con
    solo_apuestas=True: de ahí en más se sigue lo suyo que tenga foto O
    link (no ambas, alguna alcanza) -- porque eso es lo que parece una
    apuesta. Distinto de requiere_foto/requiere_link, que exigen cada
    condición por separado y se configuran a mano."""

    def _fuente(self, **kw):
        base = {"autores": "", "requiere_foto": 0, "requiere_link": 0,
                "palabras": "", "casas": "", "solo_apuestas": 1}
        base.update(kw)
        return base

    def test_pasa_con_solo_foto(self):
        from app.lector.filtros import pasa

        assert pasa(self._fuente(), "mirá esto", "Ludo", True)

    def test_pasa_con_solo_link(self):
        from app.lector.filtros import pasa

        assert pasa(self._fuente(), "https://pba.stake.bet.ar/x", "Ludo", False)

    def test_no_pasa_sin_ninguna_de_las_dos(self):
        """Un comentario de charla sin foto ni link no es una apuesta."""
        from app.lector.filtros import pasa

        assert not pasa(self._fuente(), "que buen partido", "Ludo", False)

    def test_sigue_filtrando_por_autor(self):
        from app.lector.filtros import pasa

        f = self._fuente(autores="Ludo")
        assert not pasa(f, "https://x.com", "Otro", False)


class TestAgregarAutorAFuente:
    """Ahora exige id: agregar sin id reintroduciría la ambigüedad de
    nombre que este mecanismo vino a resolver."""

    def test_suma_un_autor_nuevo_con_id(self, db):
        db.agregar_fuente("MLB", "grupo_mlb", autor_ids="111:Tole")
        db.agregar_autor_a_fuente("grupo_mlb", "Ludo", autor_id=222)
        assert db.listar_fuentes()[0]["autor_ids"] == "111:Tole,222:Ludo"

    def test_no_duplica_si_ya_estaba_el_id(self, db):
        db.agregar_fuente("MLB", "grupo_mlb", autor_ids="111:Ludo")
        db.agregar_autor_a_fuente("grupo_mlb", "Ludo", autor_id=111)
        assert db.listar_fuentes()[0]["autor_ids"] == "111:Ludo"

    def test_sin_id_no_agrega_nada(self, db):
        """Sin id no hay forma confiable de identificar a la persona
        después -- mejor no guardarlo que guardarlo ambiguo."""
        db.agregar_fuente("MLB", "grupo_mlb", autor_ids="111:Ludo")
        db.agregar_autor_a_fuente("grupo_mlb", "Otro", autor_id=None)
        assert db.listar_fuentes()[0]["autor_ids"] == "111:Ludo"

    def test_fuente_inexistente_no_rompe(self, db):
        db.agregar_autor_a_fuente("no_existe", "Juan")  # no debe lanzar


class TestFiltroPorId:
    """Bug real, reportado con captura: alguien que se llama "C" pasaba
    el filtro de una fuente que seguía a "Cara Roja" y "leandro",
    porque "c" es subcadena de "cara roja". El nombre es ambiguo; el id
    de Telegram no. Las fuentes creadas por reacción ahora filtran por
    id, y el nombre solo queda como respaldo para las configuradas a
    mano con /fuentes."""

    def test_c_ya_no_cuela_como_cara_roja(self):
        from app.lector.filtros import pasa

        fuente = {"autores": "Cara Roja,leandro", "autor_ids": "111,222",
                  "solo_apuestas": 1}
        assert not pasa(fuente, "pick de otro", "C", True, autor_id=999)

    def test_la_persona_real_si_pasa(self):
        from app.lector.filtros import pasa

        fuente = {"autores": "Cara Roja,leandro", "autor_ids": "111,222",
                  "solo_apuestas": 1}
        assert pasa(fuente, "pick", "Cara Roja", True, autor_id=111)

    def test_reconoce_aunque_cambie_de_nombre(self):
        """El id no cambia aunque la persona cambie su nombre de
        Telegram; el filtro por nombre sí se rompería."""
        from app.lector.filtros import pasa

        fuente = {"autores": "Cara Roja,leandro", "autor_ids": "111,222",
                  "solo_apuestas": 1}
        assert pasa(fuente, "pick", "Nombre Nuevo Random", True, autor_id=111)

    def test_sin_ids_cae_al_nombre_como_antes(self):
        """Fuentes configuradas a mano con /fuentes autor: no tienen
        id -- ahí sigue valiendo el nombre, es lo único que hay."""
        from app.lector.filtros import pasa

        fuente = {"autores": "Ludo", "autor_ids": ""}
        assert pasa(fuente, "pick", "Ludo Gallina", False)

    def test_autor_id_permitido_exacto(self):
        from app.lector.filtros import autor_id_permitido

        assert autor_id_permitido(111, "111,222")
        assert not autor_id_permitido(999, "111,222")
        assert not autor_id_permitido(None, "111,222")

    def test_sin_ids_configurados_pasa_cualquiera(self):
        from app.lector.filtros import autor_id_permitido

        assert autor_id_permitido(123, "")
        assert autor_id_permitido(None, "")


class TestQuitarUnaPersonaSinAfectarAlResto:
    """Lo que pediste: separar por persona y poder sacar solo a una."""

    def test_saca_solo_a_esa_persona(self, db):
        db.agregar_fuente("Grupo", "g1", autor_ids="111:Cara Roja,222:leandro,333:Tin",
                          solo_apuestas=True)
        resultado = db.quitar_autor_de_fuente("g1", 333)
        assert resultado == "autor"
        f = db.listar_fuentes()[0]
        assert f["autor_ids"] == "111:Cara Roja,222:leandro"
        assert "Tin" not in f["autores"]

    def test_las_demas_personas_siguen_intactas(self, db):
        db.agregar_fuente("Grupo", "g1", autor_ids="111:Cara Roja,222:leandro",
                          solo_apuestas=True)
        db.quitar_autor_de_fuente("g1", 111)
        f = db.listar_fuentes()[0]
        assert "leandro" in f["autores"]
        assert "222" in f["autor_ids"]

    def test_si_era_la_ultima_persona_deja_de_seguir_el_grupo_entero(self, db):
        """Un filtro "solo apuestas" sin nadie a quien aplicarle no
        tiene sentido -- y dejarlo vacío caería en "sin filtros, pasa
        todo", que es peor."""
        db.agregar_fuente("Grupo", "g1", autor_ids="111:Cara Roja", solo_apuestas=True)
        resultado = db.quitar_autor_de_fuente("g1", 111)
        assert resultado == "fuente"
        assert db.listar_fuentes() == []

    def test_persona_inexistente_no_hace_nada(self, db):
        db.agregar_fuente("Grupo", "g1", autor_ids="111:Cara Roja", solo_apuestas=True)
        assert db.quitar_autor_de_fuente("g1", 999) == "nada"

    def test_grupo_inexistente_no_rompe(self, db):
        assert db.quitar_autor_de_fuente("no-existe", 111) == "nada"
