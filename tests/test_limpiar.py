"""/limpiar: vaciar los resultados calculados por la versión con bugs.

El resolutor viejo marcaba como ganados combos que en realidad se
perdieron, y esos veredictos quedaron guardados. Como el código sólo
resuelve los combos que están SIN resolver, sin limpiarlos seguirían
mintiendo para siempre.
"""
import json

import pytest

from app.db import database


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/l.db")
    monkeypatch.setattr(database, "_db_path", lambda: str(tmp_path / "l.db"))
    database.init_db()
    return database


def _combo(db, chat_id, resultado):
    with db._connection() as conn:
        conn.execute(
            "INSERT INTO combos_sugeridos "
            "(chat_id, tipo, legs_json, cuota, probabilidad, creado_en, resultado) "
            "VALUES (?, 'sonadora', ?, 10.0, 40.0, '2026-07-30T12:00:00+00:00', ?)",
            (chat_id, json.dumps([{"player": "X"}]), resultado),
        )


class TestLimpiarResultadosCombos:
    def test_borra_los_resultados_pero_no_los_combos(self, db):
        _combo(db, 1, "ganada")
        _combo(db, 1, "perdida")
        _combo(db, 1, None)

        borrados = db.limpiar_resultados_combos(1)
        assert borrados == 2  # solo los que tenían resultado

        combos = db.listar_combos_sugeridos(1)
        assert len(combos) == 3, "borró combos, tenía que borrar sólo los resultados"
        assert all(c["resultado"] is None for c in combos)

    def test_no_toca_los_combos_de_otro_chat(self, db):
        _combo(db, 1, "ganada")
        _combo(db, 2, "ganada")

        db.limpiar_resultados_combos(1)
        assert db.listar_combos_sugeridos(2)[0]["resultado"] == "ganada"


class TestLimpiarCalibracion:
    def test_borra_las_legs_registradas(self, db):
        db.registrar_legs_resueltas(1, "t1", [
            {"jugador": "A", "mercado": "Hits", "linea": "Over 0.5",
             "prob_estimada": 70, "se_dio": True},
        ])
        assert db.resumen_calibracion(1)["total"] == 1

        db.limpiar_legs_resueltas(1)
        assert db.resumen_calibracion(1)["total"] == 0

    def test_no_toca_la_calibracion_de_otro_chat(self, db):
        for chat in (1, 2):
            db.registrar_legs_resueltas(chat, "t1", [
                {"jugador": "A", "mercado": "Hits", "linea": "Over 0.5",
                 "prob_estimada": 70, "se_dio": True},
            ])
        db.limpiar_legs_resueltas(1)
        assert db.resumen_calibracion(2)["total"] == 1
