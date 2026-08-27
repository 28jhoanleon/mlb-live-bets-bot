"""Borradores visibles en la web, con botones para decidir.

Un talón armado pero no jugado se guarda MARCADO: se ve en la web (que
es más cómoda para comparar) sin mezclarse con las apuestas reales. Desde
ahí se confirma o se descarta.
"""
import pytest

from app.db import database
from app.web.service import _ticket_id


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/b.db")
    monkeypatch.setattr(database, "_db_path", lambda: str(tmp_path / "b.db"))
    database.init_db()
    return database


def _apuesta(borrador=False, n=1):
    tickets = []
    for i in range(n):
        # Los tickets tienen que diferenciarse por JUGADOR, no por
        # partido: el partido no entra en el id (se deduce y se
        # sobreescribe, así que no es estable).
        t = {"legs": [{"match": f"A{i} @ B{i}", "player": f"Jugador {i}",
                       "market": "batter_hits", "line": "Over 0.5"}],
             "total_odds": "2.0"}
        if borrador:
            t["borrador"] = True
        tickets.append(t)
    return {"bets": tickets, "is_live": False}


class TestConfirmarBorrador:
    def test_deja_de_ser_borrador(self, db):
        db.save_active_bet(1, _apuesta(borrador=True))
        tid = _ticket_id(db.get_active_bet(1)["bets"][0],
                         db.get_active_bet(1)["bets"][0]["legs"])

        assert db.confirmar_borrador(1, tid, _ticket_id) is True
        assert "borrador" not in db.get_active_bet(1)["bets"][0]

    def test_no_toca_una_apuesta_que_ya_era_real(self, db):
        db.save_active_bet(1, _apuesta(borrador=False))
        t = db.get_active_bet(1)["bets"][0]
        assert db.confirmar_borrador(1, _ticket_id(t, t["legs"]), _ticket_id) is False

    def test_id_inexistente_no_rompe(self, db):
        db.save_active_bet(1, _apuesta(borrador=True))
        assert db.confirmar_borrador(1, "no-existe", _ticket_id) is False


class TestDescartarTicket:
    def test_saca_solo_ese_ticket(self, db):
        db.save_active_bet(1, _apuesta(borrador=True, n=3))
        tickets = db.get_active_bet(1)["bets"]
        tid = _ticket_id(tickets[1], tickets[1]["legs"])

        assert db.descartar_ticket(1, tid, _ticket_id) is True
        restantes = db.get_active_bet(1)["bets"]
        assert len(restantes) == 2
        assert all(_ticket_id(t, t["legs"]) != tid for t in restantes)

    def test_descartar_el_ultimo_limpia_todo(self, db):
        db.save_active_bet(1, _apuesta(borrador=True))
        t = db.get_active_bet(1)["bets"][0]
        db.descartar_ticket(1, _ticket_id(t, t["legs"]), _ticket_id)
        assert db.get_active_bet(1) is None


class TestBorradoresFueraDeCalibracion:
    def test_el_codigo_excluye_los_borradores(self):
        """Medir el modelo contra apuestas que nunca se jugaron
        contaminaría la calibración."""
        import pathlib

        fuente = pathlib.Path("app/web/service.py").read_text()
        assert 'if terminado and not ticket.get("borrador"):' in fuente, (
            "los borradores volverían a contar para calibración"
        )


class TestLaMarcaSobreviveANormalize:
    """Bug real: el bot decía "guardada como borrador" pero en la web
    aparecía como apuesta normal, sin cartel ni botones.

    normalize() reconstruye cada ticket con una lista fija de campos, y
    cualquier campo que no esté en esa lista se pierde en silencio. La
    marca de borrador era uno de ellos."""

    def test_normalize_conserva_el_borrador(self):
        from app.analysis.tickets import normalize

        analysis = {"bets": [{
            "total_odds": "7.25",
            "borrador": True,
            "legs": [{"match": "A @ B", "player": "X",
                      "market": "batter_hits", "line": "Over 0.5"}],
        }], "is_live": False}

        tickets = normalize(analysis)
        assert tickets, "normalize devolvió vacío"
        assert tickets[0]["borrador"] is True, (
            "se perdió la marca: la web lo muestra como apuesta real"
        )

    def test_una_apuesta_normal_no_queda_marcada(self):
        from app.analysis.tickets import normalize

        analysis = {"bets": [{
            "total_odds": "7.25",
            "legs": [{"match": "A @ B", "player": "X",
                      "market": "batter_hits", "line": "Over 0.5"}],
        }], "is_live": False}
        assert normalize(analysis)[0]["borrador"] is False


class TestElFlagSobreviveANormalize:
    """Bug real: el borrador se guardaba bien, pero `normalize` --que
    reconstruye cada ticket con una lista FIJA de campos-- descartaba la
    marca. Llegaba a la web como apuesta normal: sin cartel y sin los
    botones de confirmar o descartar."""

    def test_normalize_conserva_la_marca(self):
        from app.analysis.tickets import normalize

        analisis = {"bets": [{
            "legs": [{"match": "A @ B", "player": "X",
                      "market": "batter_hits", "line": "Over 0.5"}],
            "total_odds": "7.25", "borrador": True,
        }], "is_live": False}

        assert all(t.get("borrador") for t in normalize(analisis))

    def test_una_apuesta_normal_no_queda_marcada(self):
        from app.analysis.tickets import normalize

        analisis = {"bets": [{
            "legs": [{"match": "A @ B", "player": "X",
                      "market": "batter_hits", "line": "Over 0.5"}],
            "total_odds": "7.25",
        }], "is_live": False}

        assert not any(t.get("borrador") for t in normalize(analisis))

    def test_sobrevive_aunque_el_ticket_se_divida_por_partido(self):
        """Una combinada de varios partidos se parte en varios tickets:
        todos tienen que conservar la marca."""
        from app.analysis.tickets import normalize

        analisis = {"bets": [{
            "legs": [
                {"match": "A @ B", "player": "X", "market": "batter_hits", "line": "Over 0.5"},
                {"match": "C @ D", "player": "Y", "market": "batter_hits", "line": "Over 0.5"},
            ],
            "total_odds": "7.25", "borrador": True,
        }], "is_live": False}

        tickets = normalize(analisis)
        assert tickets
        assert all(t.get("borrador") for t in tickets)


class TestElBotonBorrarUsaElIdCorrecto:
    """Bug real: la × no borraba nada. Mandaba `clave` -el id interno
    que usa el navegador para acordarse de qué tickets están colapsados-
    en vez de `t.id`, que es el que calcula el servidor. El endpoint
    buscaba ese id, no lo encontraba, y devolvía 404 en silencio.

    Son dos identificadores parecidos con propósitos distintos: fácil de
    confundir, invisible cuando se confunde."""

    def _html(self):
        import pathlib

        return pathlib.Path("app/web/static/index.html").read_text()

    def test_todas_las_acciones_mandan_el_id_del_servidor(self):
        import re

        llamadas = re.findall(r"accionTicket\('\$\{esc\(([^)]+)\)\}'", self._html())
        assert llamadas, "no encontré ninguna llamada a accionTicket"
        assert all(c == "t.id" for c in llamadas), (
            f"alguna acción manda un id que el servidor no conoce: {llamadas}"
        )

    def test_el_servidor_expone_ese_id(self):
        import pathlib

        fuente = pathlib.Path("app/web/service.py").read_text()
        assert '"id": ticket_id,' in fuente, (
            "el servidor dejó de mandar el id: los botones quedarían sin efecto"
        )


class TestBorrarUnTicketDividido:
    """Bug real: el botón × no borraba nada.

    La web no muestra los tickets tal como están guardados: pasan por
    normalize(), que puede partir uno en varios (uno por partido). Los
    ids que ve el usuario se calculan sobre esa vista, así que no
    existen en la versión guardada — y la búsqueda no encontraba nada.
    """

    def _con_dos_partidos(self, db):
        # Sin total_odds ni group_odds: normalize lo parte en dos.
        db.save_active_bet(1, {"bets": [{"legs": [
            {"match": "A @ B", "player": "X", "market": "batter_hits", "line": "Over 0.5"},
            {"match": "C @ D", "player": "Y", "market": "batter_hits", "line": "Over 0.5"},
        ]}], "is_live": False})

    def test_los_ids_de_la_web_no_coinciden_con_los_guardados(self, db):
        """Demuestra por qué fallaba."""
        from app.analysis.tickets import normalize

        self._con_dos_partidos(db)
        guardado = db.get_active_bet(1)
        ids_guardado = {_ticket_id(t, t.get("legs", [])) for t in guardado["bets"]}
        ids_web = {_ticket_id(t, t.get("legs", [])) for t in normalize(guardado)}
        assert not (ids_guardado & ids_web)

    def test_borra_usando_el_id_que_ve_el_usuario(self, db):
        from app.analysis.tickets import normalize

        self._con_dos_partidos(db)
        vista = normalize(db.get_active_bet(1))
        objetivo = _ticket_id(vista[0], vista[0]["legs"])

        assert db.descartar_ticket(1, objetivo, _ticket_id) is True
        assert len(normalize(db.get_active_bet(1))) == 1

    def test_borrar_el_unico_limpia_todo(self, db):
        db.save_active_bet(1, {"bets": [{"total_odds": "2.0", "legs": [
            {"match": "A @ B", "player": "X", "market": "batter_hits", "line": "Over 0.5"},
        ]}], "is_live": False})
        from app.analysis.tickets import normalize

        vista = normalize(db.get_active_bet(1))
        db.descartar_ticket(1, _ticket_id(vista[0], vista[0]["legs"]), _ticket_id)
        assert db.get_active_bet(1) is None

    def test_un_id_inexistente_no_borra_nada(self, db):
        self._con_dos_partidos(db)
        assert db.descartar_ticket(1, "no-existe", _ticket_id) is False


class TestCuotaManual:
    """La IA no siempre encuentra la cuota en la captura: algunos cupones
    no la muestran o queda cortada. Sin poder corregirla a mano, la
    apuesta quedaba para siempre como "Sin cuota leída"."""

    def _sin_cuota(self, db):
        db.save_active_bet(1, {"bets": [{"legs": [
            {"match": "A @ B", "player": "X", "market": "batter_hits", "line": "Over 0.5"},
        ]}], "is_live": False})
        from app.analysis.tickets import normalize

        vista = normalize(db.get_active_bet(1))
        return _ticket_id(vista[0], vista[0]["legs"])

    def test_se_puede_fijar(self, db):
        tid = self._sin_cuota(db)
        assert db.fijar_cuota_ticket(1, tid, "15.67", _ticket_id) is True

        from app.analysis.tickets import normalize

        assert normalize(db.get_active_bet(1))[0]["total_odds"] == "15.67"

    def test_un_id_inexistente_no_hace_nada(self, db):
        self._sin_cuota(db)
        assert db.fijar_cuota_ticket(1, "no-existe", "2.0", _ticket_id) is False

    def test_el_endpoint_valida_el_rango(self):
        """Una cuota de 0.5 o de un millón es un error de tipeo."""
        import pathlib

        fuente = pathlib.Path("app/web/api.py").read_text()
        assert "1.01 <= valor <= 100000" in fuente

    def test_acepta_coma_decimal(self):
        """En Argentina se escribe 15,67."""
        import pathlib

        fuente = pathlib.Path("app/web/api.py").read_text()
        assert '.replace(",", ".")' in fuente


class TestElIdNoCambiaAlDeducirElPartido:
    """Bug real: el botón × devolvía "No se pudo aplicar el cambio".

    Cuando el cupón no trae el partido, se deduce del jugador y se
    ESCRIBE en la leg. Como el partido formaba parte del identificador,
    el id que mostraba la web (ya con el partido deducido) era distinto
    del que se recalculaba al borrar (leyendo de la base, sin él). Nunca
    coincidían, así que no encontraba la apuesta.
    """

    def test_el_id_es_el_mismo_con_y_sin_partido(self):
        ticket = {"total_odds": "25.31"}
        sin = [{"player": "Yandy Diaz", "market": "batter_hits", "line": "Over 0.5"}]
        con = [{"player": "Yandy Diaz", "market": "batter_hits", "line": "Over 0.5",
                "match": "Tampa Bay Rays @ Detroit Tigers"}]
        assert _ticket_id(ticket, sin) == _ticket_id(ticket, con)

    def test_sigue_distinguiendo_apuestas_distintas(self):
        """El id tiene que seguir siendo único: si dos apuestas dieran
        el mismo, borrar una borraría la otra."""
        a = [{"player": "Judge", "market": "batter_hits", "line": "Over 0.5"}]
        b = [{"player": "Ohtani", "market": "batter_hits", "line": "Over 0.5"}]
        assert _ticket_id({}, a) != _ticket_id({}, b)

    def test_distingue_por_linea(self):
        a = [{"player": "Judge", "market": "batter_hits", "line": "Over 0.5"}]
        b = [{"player": "Judge", "market": "batter_hits", "line": "Over 1.5"}]
        assert _ticket_id({}, a) != _ticket_id({}, b)

    def test_distingue_por_cuota(self):
        legs = [{"player": "Judge", "market": "batter_hits", "line": "Over 0.5"}]
        assert _ticket_id({"total_odds": "2.0"}, legs) != _ticket_id({"total_odds": "3.0"}, legs)

    def test_borrar_funciona_con_el_partido_deducido(self, db):
        """El caso completo, de punta a punta."""
        from app.analysis.tickets import normalize

        db.save_active_bet(1, {"bets": [{"total_odds": "25.31", "legs": [
            {"player": "Yandy Diaz", "market": "batter_hits", "line": "Over 0.5"},
        ]}], "is_live": False})

        # La web muestra el id calculado sobre legs YA con partido.
        vista = normalize(db.get_active_bet(1))
        con_partido = [dict(l, match="Rays @ Tigers") for l in vista[0]["legs"]]
        id_visible = _ticket_id(vista[0], con_partido)

        assert db.descartar_ticket(1, id_visible, _ticket_id) is True
        assert db.get_active_bet(1) is None
