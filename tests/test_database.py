"""Tests de la capa de persistencia. Usa un archivo de DB temporal por
test, para no pisar la base real del bot."""
import os
import tempfile

import pytest


@pytest.fixture
def db_module(monkeypatch):
    """Crea un módulo database.py apuntando a un archivo temporal, para
    no ensuciar la DB real ni depender de que exista config real."""
    tmp_path = tempfile.mktemp(suffix=".db")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}")

    # Reimportamos con la config parcheada
    import importlib

    from app import config as config_module

    importlib.reload(config_module)
    from app.db import database as db

    importlib.reload(db)
    db.init_db()

    yield db

    if os.path.exists(tmp_path):
        os.remove(tmp_path)


def test_active_bet_roundtrip(db_module):
    analysis = {"is_parlay": True, "legs": [{"player": "Fulano"}]}
    db_module.save_active_bet(111, analysis)
    assert db_module.get_active_bet(111) == analysis


def test_active_bet_missing_returns_none(db_module):
    assert db_module.get_active_bet(999999) is None


def test_active_bet_overwrite(db_module):
    db_module.save_active_bet(111, {"legs": [{"player": "A"}]})
    db_module.save_active_bet(111, {"legs": [{"player": "B"}]})
    result = db_module.get_active_bet(111)
    assert result["legs"][0]["player"] == "B"


def test_bet_history_records_entries(db_module):
    """El test viejo usaba una estructura INVENTADA ({"legs": [...],
    "is_parlay": ...}) que el código nunca produce: lo que se guarda de
    verdad es {"bets": [{"legs": [...]}]}. Por eso pasaba en verde
    mientras /historial mostraba "Apuesta simple — ?" para todo.

    Ahora usa la forma que devuelve to_storage()."""
    from app.analysis.tickets import to_storage

    analysis = to_storage([
        {"legs": [{"match": "Team A vs Team B", "player": "X"}], "total_odds": "1.90"},
    ])
    db_module.log_bet_analysis(222, analysis)
    history = db_module.get_bet_history(222)
    assert len(history) == 1
    assert history[0]["match_summary"] == "Team A vs Team B"


def test_bet_history_marca_combinadas(db_module):
    from app.analysis.tickets import to_storage

    analysis = to_storage([
        {"legs": [
            {"match": "A vs B", "player": "X"},
            {"match": "C vs D", "player": "Y"},
        ]},
    ])
    db_module.log_bet_analysis(223, analysis)
    fila = db_module.get_bet_history(223)[0]
    assert fila["is_parlay"] == 1
    # Con varios partidos, el resumen indica cuántos más hay
    assert "+1" in fila["match_summary"]


def test_alert_subscription_toggle(db_module):
    assert db_module.is_subscribed(333) is False
    db_module.subscribe_alerts(333)
    assert db_module.is_subscribed(333) is True
    assert 333 in db_module.get_subscribed_chats()
    db_module.unsubscribe_alerts(333)
    assert db_module.is_subscribed(333) is False


def test_alert_dedup(db_module):
    assert db_module.has_seen_alert("key-1") is False
    db_module.mark_alert_seen("key-1")
    assert db_module.has_seen_alert("key-1") is True
