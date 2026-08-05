"""Auditoría de tickets: marcar tramos flojos y proponer reemplazos."""
from dataclasses import dataclass
from unittest.mock import patch

from app.analysis import auditoria as aud
from app.analysis.auditoria import armar_mejorada, auditar_legs, proponer_reemplazos
from app.analysis.probability import LegEstimate, ProbabilityError


@dataclass
class PickFalso:
    player: str
    market: str = "batter_hits"
    line: str = "Over 0.5"
    odds: float = 1.8
    our_probability_pct: float = 85.0
    market_probability_pct: float = 55.0
    edge_pct: float = 30.0
    sample_size: int = 10
    commence_time: str | None = None


def _est(nombre, prob):
    return LegEstimate(player=nombre, market="Hits", side="Over", threshold=0.5,
                       probability_pct=prob, sample_size=10, avg_value=1.2,
                       is_pitcher=False)


class TestAuditarLegs:
    def test_clasifica_flojas_y_fuertes(self):
        legs = [{"player": "Fuerte", "market": "Hits", "line": "Over 0.5"},
                {"player": "Flojo", "market": "Hits", "line": "Over 0.5"}]
        probs = {"Fuerte": 80.0, "Flojo": 30.0}

        with patch.object(aud, "estimate_leg_probability",
                          side_effect=lambda p, m, l: _est(p, probs[p])):
            a = auditar_legs(legs)

        assert [l.player for l in a.fuertes] == ["Fuerte"]
        assert [l.player for l in a.flojas] == ["Flojo"]

    def test_combina_las_probabilidades(self):
        legs = [{"player": "A", "market": "Hits", "line": "Over 0.5"},
                {"player": "B", "market": "Hits", "line": "Over 0.5"}]
        with patch.object(aud, "estimate_leg_probability",
                          side_effect=lambda p, m, l: _est(p, 50.0)):
            a = auditar_legs(legs)
        assert a.probabilidad_combinada == 25.0  # 0.5 * 0.5

    def test_una_leg_sin_datos_no_rompe_la_auditoria(self):
        legs = [{"player": "A", "market": "Hits", "line": "Over 0.5"},
                {"player": "Fantasma", "market": "Hits", "line": "Over 0.5"}]

        def _lado(p, m, l):
            if p == "Fantasma":
                raise ProbabilityError("no lo encuentro")
            return _est(p, 80.0)

        with patch.object(aud, "estimate_leg_probability", side_effect=_lado):
            a = auditar_legs(legs)

        assert len(a.sin_datos) == 1
        # Sin todas las legs estimadas no se inventa una combinada
        assert a.probabilidad_combinada is None

    def test_mercado_de_equipo_se_lista_pero_no_se_estima(self):
        a = auditar_legs([{"player": None, "market": "Strikeouts", "line": "Under 14.5"}])
        assert len(a.sin_datos) == 1
        assert "equipo" in a.legs[0].error


class TestProponerReemplazos:
    def test_propone_solo_para_las_flojas(self):
        legs = [{"player": "Flojo", "market": "Hits", "line": "Over 0.5"},
                {"player": "Fuerte", "market": "Hits", "line": "Over 0.5"}]
        probs = {"Flojo": 30.0, "Fuerte": 80.0}
        with patch.object(aud, "estimate_leg_probability",
                          side_effect=lambda p, m, l: _est(p, probs[p])):
            a = auditar_legs(legs)

        props = proponer_reemplazos(a, [PickFalso("Nuevo")])
        assert len(props) == 1
        assert props[0][0].player == "Flojo"

    def test_no_propone_un_jugador_que_ya_esta_en_el_ticket(self):
        """Repetir jugador concentra el riesgo en vez de repartirlo."""
        legs = [{"player": "Flojo", "market": "Hits", "line": "Over 0.5"}]
        with patch.object(aud, "estimate_leg_probability",
                          side_effect=lambda p, m, l: _est(p, 30.0)):
            a = auditar_legs(legs)

        assert proponer_reemplazos(a, [PickFalso("Flojo")]) == []

    def test_no_propone_algo_apenas_mejor(self):
        """Cambiar 40% por 45% no justifica rehacer la apuesta."""
        legs = [{"player": "Flojo", "market": "Hits", "line": "Over 0.5"}]
        with patch.object(aud, "estimate_leg_probability",
                          side_effect=lambda p, m, l: _est(p, 40.0)):
            a = auditar_legs(legs)
        assert proponer_reemplazos(a, [PickFalso("Nuevo", our_probability_pct=45.0)]) == []


class TestArmarMejorada:
    def test_conserva_las_buenas_y_reemplaza_las_flojas(self):
        legs = [{"player": "Fuerte", "market": "Hits", "line": "Over 0.5"},
                {"player": "Flojo", "market": "Hits", "line": "Over 0.5"}]
        probs = {"Fuerte": 80.0, "Flojo": 25.0}
        with patch.object(aud, "estimate_leg_probability",
                          side_effect=lambda p, m, l: _est(p, probs[p])):
            a = auditar_legs(legs)

        mejorada = armar_mejorada(a, [PickFalso("Nuevo")])
        nombres = [x.player for x in mejorada]
        assert "Fuerte" in nombres, "descartó un tramo que estaba bien"
        assert "Flojo" not in nombres
        assert "Nuevo" in nombres

    def test_sin_reemplazos_deja_la_leg_original(self):
        """Mejor dejarla como está que meter cualquier cosa."""
        legs = [{"player": "Flojo", "market": "Hits", "line": "Over 0.5"}]
        with patch.object(aud, "estimate_leg_probability",
                          side_effect=lambda p, m, l: _est(p, 30.0)):
            a = auditar_legs(legs)
        assert [x.player for x in armar_mejorada(a, [])] == ["Flojo"]

    def test_no_repite_el_mismo_pick_en_dos_tramos(self):
        legs = [{"player": "Flojo1", "market": "Hits", "line": "Over 0.5"},
                {"player": "Flojo2", "market": "Hits", "line": "Over 0.5"}]
        with patch.object(aud, "estimate_leg_probability",
                          side_effect=lambda p, m, l: _est(p, 25.0)):
            a = auditar_legs(legs)

        mejorada = armar_mejorada(a, [PickFalso("Unico")])
        nombres = [x.player for x in mejorada]
        assert nombres.count("Unico") == 1, "usó el mismo pick para dos tramos"
