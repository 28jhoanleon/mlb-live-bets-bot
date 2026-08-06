"""El modelo estimaba probabilidades infladas 3-6x contra el mercado.

Caso real: soñadoras a cuota 10.68 (el mercado paga como 9.4%) donde el
bot decía 54%. Dos errores estadísticos que se potenciaban:

1. Tomar "9 de sus últimos 10" como 90% de probabilidad. Con esa muestra
   el número está sobreajustado a la racha reciente, y "10 de 10" daba
   100%, que nunca es cierto.
2. Multiplicar las legs como si fueran independientes. Comparten día,
   condiciones y a veces el mismo partido: el producto crudo sobreestima,
   y cada leg extra acumula más error.
"""
from unittest.mock import patch

from app.analysis import probability as prob


def _estimar(aciertos: int, total: int) -> float:
    juegos = [{"date": f"2026-08-{i+1:02d}", "hits": 1 if i < aciertos else 0}
              for i in range(total)]
    prob.limpiar_cache_estimaciones()
    with patch.object(prob, "search_player",
                      return_value={"id": 1, "full_name": "X", "position": "Hitter"}), \
         patch.object(prob, "get_recent_hitting_games", return_value=juegos):
        return prob.estimate_leg_probability("X", "batter_hits", "Over 0.5").probability_pct


class TestSuavizado:
    def test_nunca_devuelve_100_por_ciento(self):
        """Una racha perfecta no significa certeza: con 10 partidos no
        alcanza para afirmar que SIEMPRE va a pasar."""
        assert _estimar(10, 10) < 100.0

    def test_una_muestra_chica_pesa_menos(self):
        """4 de 4 no puede valer lo mismo que 40 de 40."""
        assert _estimar(4, 4) < _estimar(40, 40)

    def test_mantiene_el_orden(self):
        """El suavizado corrige la magnitud, no da vuelta el ranking."""
        assert _estimar(9, 10) > _estimar(7, 10) > _estimar(5, 10)

    def test_corrige_hacia_abajo_las_rachas_buenas(self):
        assert _estimar(9, 10) < 90.0

    def test_corrige_hacia_arriba_las_rachas_malas(self):
        """Simétrico: 1 de 10 tampoco es 10%."""
        assert _estimar(1, 10) > 10.0


class TestPenalizacionPorDependencia:
    def _combo(self, n_legs, mismo_partido):
        from app.analysis.combos import ComboLeg, _build_combo

        legs = tuple(
            ComboLeg(
                match="A @ B" if mismo_partido else f"Partido {i}",
                player=f"Jugador {i}", market="batter_hits", line="Over 0.5",
                odds=1.5, probability_pct=80.0, sample_size=10,
            )
            for i in range(n_legs)
        )
        return _build_combo(legs)

    def test_penaliza_mas_al_mismo_partido(self):
        """Legs del mismo juego comparten hasta el pitcher rival."""
        assert (self._combo(3, True).combined_probability_pct
                < self._combo(3, False).combined_probability_pct)

    def test_mas_legs_mas_penalizacion(self):
        """El error de suponer independencia se acumula."""
        crudo_2 = 0.8 ** 2 * 100
        crudo_4 = 0.8 ** 4 * 100
        desvio_2 = crudo_2 - self._combo(2, False).combined_probability_pct
        desvio_4 = crudo_4 - self._combo(4, False).combined_probability_pct
        assert desvio_4 > desvio_2

    def test_el_valor_esperado_usa_la_probabilidad_corregida(self):
        """Calcular el EV con la probabilidad inflada mostraría valor
        donde no lo hay, que es lo peligroso del bug."""
        combo = self._combo(4, False)
        ev_esperado = (combo.combined_probability_pct / 100 * combo.combined_odds - 1) * 100
        assert abs(combo.expected_value_pct - ev_esperado) < 0.5
