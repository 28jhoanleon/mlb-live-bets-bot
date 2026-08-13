"""Dos problemas que hacían inútiles las soñadoras aunque el cálculo
estuviera bien.

1. TODAS las legs mostraban exactamente 91.7%. Con una muestra de 10
   partidos el suavizado solo puede producir 12 valores distintos, y
   como el ranking ordena por ventaja, el máximo (10 de 10 = 91.7%)
   ganaba siempre: los picks quedaban empatados y no se distinguían.

2. Las tres soñadoras compartían 3 de sus 4 tramos. Eran la misma
   apuesta con una pata cambiada, así que no ofrecían alternativas.
"""
from app.analysis.combos import ComboLeg, find_dream_combos
from app.analysis.probability import _DEFAULT_SAMPLE


class TestMuestraSuficiente:
    def test_la_muestra_permite_distinguir_jugadores(self):
        """Con 10 partidos, 9/10 y 10/10 son de los pocos valores altos
        posibles y todo se amontona arriba."""
        assert _DEFAULT_SAMPLE >= 20, (
            "muestra demasiado chica: los picks buenos empatan todos en "
            "el mismo porcentaje y el ranking no los diferencia"
        )

    def test_hay_mas_valores_altos_disponibles(self):
        """Cuántos porcentajes distintos hay entre 70% y 100%: con 10
        partidos son 3, y por eso se repetían."""
        n = _DEFAULT_SAMPLE
        altos = [(h + 1) / (n + 2) for h in range(n + 1) if (h + 1) / (n + 2) >= 0.70]
        assert len(altos) >= 7, f"solo {len(altos)} valores altos posibles"


def _leg(nombre, prob=85.0, cuota=2.5, partido=None):
    return ComboLeg(
        match=partido or f"Partido de {nombre}", player=nombre,
        market="batter_hits", line="Over 0.5", odds=cuota,
        probability_pct=prob, sample_size=25, commence_time=None,
    )


class TestVariedadEntreSonadoras:
    def test_no_repite_casi_los_mismos_jugadores(self, monkeypatch):
        """El caso reportado: 3 sugerencias con 3 de 4 tramos iguales."""
        from app.analysis import combos as mod

        jugadores = [f"Jugador {i}" for i in range(12)]
        picks = [
            type("P", (), {
                "match": f"P{i} @ R{i}", "player": n, "market": "batter_hits",
                "line": "Over 0.5", "odds": 2.6, "our_probability_pct": 85.0,
                "market_probability_pct": 38.0, "edge_pct": 120.0,
                "sample_size": 25, "commence_time": None,
            })()
            for i, n in enumerate(jugadores)
        ]
        monkeypatch.setattr(mod, "find_daily_picks", lambda **kw: picks)

        resultado = find_dream_combos(max_results=3)
        if len(resultado) < 2:
            return  # sin material suficiente, nada que comprobar

        for i, a in enumerate(resultado):
            for b in resultado[i + 1:]:
                comunes = {l.player for l in a.legs} & {l.player for l in b.legs}
                assert len(comunes) <= len(a.legs) // 2, (
                    f"dos soñadoras comparten {len(comunes)} de {len(a.legs)} "
                    "tramos: son la misma apuesta con un cambio"
                )

    def test_no_repite_un_jugador_dentro_de_la_misma_sonadora(self, monkeypatch):
        from app.analysis import combos as mod

        picks = [
            type("P", (), {
                "match": f"P{i} @ R{i}", "player": f"Jugador {i}",
                "market": "batter_hits", "line": "Over 0.5", "odds": 2.6,
                "our_probability_pct": 85.0, "market_probability_pct": 38.0,
                "edge_pct": 120.0, "sample_size": 25, "commence_time": None,
            })()
            for i in range(10)
        ]
        monkeypatch.setattr(mod, "find_daily_picks", lambda **kw: picks)

        for combo in find_dream_combos(max_results=3):
            nombres = [l.player for l in combo.legs]
            assert len(nombres) == len(set(nombres))
