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
        t = {"legs": [{"match": f"A{i} @ B{i}", "player": "X",
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
