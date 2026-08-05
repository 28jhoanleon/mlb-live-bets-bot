"""Mercados de equipo/partido y borrado individual de apuestas."""
import pytest

from app.db import database
from app.web.service import _es_de_equipo, _leg_de_equipo


class TestMercadosDeEquipo:
    """Stake ofrece "Partido, ponches (strikeouts)" y "Equipo, bases por
    bolas del bateador" además de los mercados de jugador. No tienen
    jugador, así que no se pueden estimar con el historial de nadie: el
    bot los mostraba como "Sin jugador — Sin datos suficientes", que
    parecía un error suyo."""

    def test_reconoce_mercado_de_partido(self):
        leg = {"ambito": "partido", "market": "Strikeouts", "line": "Under 14.5", "player": None}
        assert _es_de_equipo(leg)
        assert _leg_de_equipo(leg)["player"] == "Todo el partido"

    def test_reconoce_mercado_de_equipo_con_su_nombre(self):
        leg = {"ambito": "equipo", "team": "Kansas City Royals",
               "market": "batter_walks", "line": "Over 2.5", "player": None}
        assert _es_de_equipo(leg)
        assert _leg_de_equipo(leg)["player"] == "Kansas City Royals"

    def test_una_leg_de_jugador_no_se_confunde(self):
        assert not _es_de_equipo(
            {"player": "Jake Burger", "market": "batter_hits", "line": "Over 0.5"}
        )

    def test_apuestas_viejas_sin_ambito_igual_se_detectan(self):
        """Las guardadas antes de que la visión extrajera "ambito" no
        tienen el campo, pero tampoco jugador."""
        assert _es_de_equipo({"market": "Strikeouts", "line": "Under 14.5", "player": None})

    def test_no_dice_sin_datos_suficientes(self):
        """Ese mensaje sugería que el bot falló; en realidad es un tipo
        de apuesta que todavía no seguimos."""
        leg = {"ambito": "partido", "market": "Strikeouts", "line": "Under 14.5"}
        assert "Sin datos suficientes" not in _leg_de_equipo(leg)["note"]
        assert "equipo" in _leg_de_equipo(leg)["note"].lower()


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/b.db")
    monkeypatch.setattr(database, "_db_path", lambda: str(tmp_path / "b.db"))
    database.init_db()
    return database


def _apuesta(n):
    return {"bets": [
        {"legs": [{"match": f"Equipo {i} @ Rival {i}", "player": "X"}], "total_odds": "2.0"}
        for i in range(n)
    ], "is_live": False}


class TestBorrarTicketPuntual:
    def test_borra_solo_el_indicado(self, db):
        db.save_active_bet(1, _apuesta(3))
        db.borrar_ticket(1, 2)

        restantes = db.get_active_bet(1)["bets"]
        assert len(restantes) == 2
        partidos = [t["legs"][0]["match"] for t in restantes]
        assert "Equipo 1 @ Rival 1" not in partidos  # el segundo (índice 1)

    def test_indice_invalido_no_borra_nada(self, db):
        db.save_active_bet(1, _apuesta(2))
        assert db.borrar_ticket(1, 99) is None
        assert len(db.get_active_bet(1)["bets"]) == 2

    def test_borrar_la_ultima_limpia_la_apuesta_activa(self, db):
        db.save_active_bet(1, _apuesta(1))
        db.borrar_ticket(1, 1)
        assert db.get_active_bet(1) is None

    def test_sin_apuestas_no_explota(self, db):
        assert db.borrar_ticket(1, 1) is None
