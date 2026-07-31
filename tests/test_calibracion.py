"""Calibración: guardar TODAS las legs resueltas, no sólo las ganadoras.

La idea original era guardar únicamente los tickets que salieran
ganadores enteros. Eso es sesgo de supervivencia: mirando sólo los
aciertos, cualquier modelo parece perfecto. Para saber si un "70%" es
honesto hay que guardar también las que fallaron.
"""
import pytest

from app.db import database


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/cal.db")
    monkeypatch.setattr(database, "_db_path", lambda: str(tmp_path / "cal.db"))
    database.init_db()
    return database


def _legs(prob, se_dio, n, prefijo):
    return [
        {"jugador": f"{prefijo}{i}", "mercado": "Hits", "linea": "Over 0.5",
         "prob_estimada": prob, "se_dio": se_dio}
        for i in range(n)
    ]


class TestRegistroDeLegs:
    def test_guarda_acertadas_y_falladas(self, db):
        db.registrar_legs_resueltas(1, "t1", _legs(70, True, 3, "a"))
        db.registrar_legs_resueltas(1, "t2", _legs(70, False, 2, "b"))
        resumen = db.resumen_calibracion(1)
        assert resumen["total"] == 5
        assert resumen["acertadas"] == 3

    def test_no_duplica_si_el_ticket_se_registra_dos_veces(self, db):
        """La web recalcula el estado en cada refresco: sin esto, un
        ticket terminado se registraría una vez por segundo."""
        legs = _legs(70, True, 3, "a")
        db.registrar_legs_resueltas(1, "t1", legs)
        db.registrar_legs_resueltas(1, "t1", legs)
        db.registrar_legs_resueltas(1, "t1", legs)
        assert db.resumen_calibracion(1)["total"] == 3


class TestDetectaModeloInflado:
    def test_modelo_inflado_se_nota(self, db):
        # Dice 80% pero acierta 4 de 10
        db.registrar_legs_resueltas(1, "t1", _legs(80, True, 4, "a"))
        db.registrar_legs_resueltas(1, "t2", _legs(80, False, 6, "b"))

        resumen = db.resumen_calibracion(1)
        assert resumen["prob_media"] == 80.0
        assert resumen["real_pct"] == 40.0

        tramos = db.calibracion(1)
        tramo80 = [t for t in tramos if t["tramo"] == "80-89%"][0]
        assert tramo80["real_pct"] == 40.0
        assert tramo80["muestra"] == 10

    def test_modelo_calibrado_da_parecido(self, db):
        db.registrar_legs_resueltas(1, "t1", _legs(70, True, 7, "a"))
        db.registrar_legs_resueltas(1, "t2", _legs(70, False, 3, "b"))
        resumen = db.resumen_calibracion(1)
        assert abs(resumen["prob_media"] - resumen["real_pct"]) <= 1

    def test_sin_datos_no_explota(self, db):
        assert db.resumen_calibracion(1)["total"] == 0
        assert db.calibracion(1) == []
