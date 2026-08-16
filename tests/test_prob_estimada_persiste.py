"""EL bug que hacía que /calibracion estuviera siempre vacío.

La probabilidad estimada de cada leg se escribe dentro del propio dict
durante el análisis (`leg["prob_estimada"]`). Es el único número honesto
para medir calibración después: lo que el bot predijo ANTES de que se
jugara.

El problema era el ORDEN. Se guardaba la apuesta en la base y RECIÉN
DESPUÉS se calculaban las probabilidades, así que ese campo se escribía
sobre un dict ya persistido y nunca llegaba a SQLite. Las apuestas se
resolvían bien, el job las registraba... con prob_estimada en NULL, y
la consulta de calibración las descarta todas. Resultado: por más que
dejaras apuestas enteras durante horas, /calibracion seguía en cero.
"""
import pathlib
import re


FUENTE = pathlib.Path("app/bot/handlers/screenshot.py").read_text()


class TestOrdenDeGuardado:
    def test_se_analiza_antes_de_guardar(self):
        pos_analisis = FUENTE.index("_format_full_analysis(analysis)")
        pos_guardado = FUENTE.index("save_active_bet(chat_id, analysis)")
        assert pos_analisis < pos_guardado, (
            "se guarda antes de calcular las probabilidades: prob_estimada "
            "no llega a la base y /calibracion queda vacío para siempre"
        )

    def test_la_probabilidad_se_escribe_en_la_leg(self):
        assert 'leg["prob_estimada"] = estimate.probability_pct' in FUENTE


class TestElCampoSobreviveAlGuardado:
    def test_normalize_lo_conserva(self):
        """normalize reconstruye cada leg: si no copia este campo, se
        pierde igual aunque el orden esté bien (ya pasó con 'borrador')."""
        from app.analysis.tickets import normalize

        analisis = {"bets": [{
            "total_odds": "3.5",
            "legs": [{"match": "A @ B", "player": "X", "market": "batter_hits",
                      "line": "Over 0.5", "prob_estimada": 78.0}],
        }], "is_live": False}

        for ticket in normalize(analisis):
            for leg in ticket["legs"]:
                assert leg.get("prob_estimada") == 78.0

    def test_sobrevive_al_viaje_por_sqlite(self, tmp_path, monkeypatch):
        """Guardar y volver a leer: es el camino real."""
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/p.db")
        from app.db import database

        monkeypatch.setattr(database, "_db_path", lambda: str(tmp_path / "p.db"))
        database.init_db()

        analisis = {"bets": [{
            "total_odds": "3.5",
            "legs": [{"match": "A @ B", "player": "X", "market": "batter_hits",
                      "line": "Over 0.5", "prob_estimada": 78.0}],
        }], "is_live": False}
        database.save_active_bet(1, analisis)

        leido = database.get_active_bet(1)
        assert leido["bets"][0]["legs"][0]["prob_estimada"] == 78.0


class TestSinProbabilidadNoHayCalibracion:
    def test_las_legs_sin_estimacion_no_cuentan(self, tmp_path, monkeypatch):
        """Demuestra por qué el bug era invisible: se registraban las
        legs igual, pero con prob_estimada en NULL, y la consulta las
        descarta. La tabla tenía filas y el resumen daba cero."""
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/q.db")
        from app.db import database

        monkeypatch.setattr(database, "_db_path", lambda: str(tmp_path / "q.db"))
        database.init_db()

        database.registrar_legs_resueltas(1, "t1", [
            {"jugador": "X", "mercado": "Hits", "linea": "Over 0.5",
             "prob_estimada": None, "se_dio": True},
        ])
        assert database.resumen_calibracion(1)["total"] == 0
        assert database.calibracion(1) == []

    def test_con_estimacion_si_cuentan(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/r.db")
        from app.db import database

        monkeypatch.setattr(database, "_db_path", lambda: str(tmp_path / "r.db"))
        database.init_db()

        database.registrar_legs_resueltas(1, "t1", [
            {"jugador": "X", "mercado": "Hits", "linea": "Over 0.5",
             "prob_estimada": 78.0, "se_dio": True},
        ])
        assert database.resumen_calibracion(1)["total"] == 1
