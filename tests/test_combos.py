"""Tests del generador de combinadas con valor.

Lo importante acá no es que genere combos, sino que RECHACE los que no
corresponden: una combinada solo tiene valor si cada leg lo tiene.
"""
from unittest.mock import patch

from app.analysis.combos import find_value_combos
from app.analysis.daily_picks import DailyPick


def _pick(match, player, prob, odds, market="batter_hits"):
    """Pick con probabilidad `prob` y cuota `odds`."""
    implicita = round(100 / odds, 1)
    return DailyPick(
        match=match,
        player=player,
        market=market,
        line="Over 0.5",
        odds=odds,
        our_probability_pct=prob,
        market_probability_pct=implicita,
        edge_pct=round(prob - implicita, 1),
        sample_size=10,
    )


def _combos(picks, **kwargs):
    with patch("app.analysis.combos.find_daily_picks", return_value=picks):
        return find_value_combos(**kwargs)


class TestFiltrosDeCalidad:
    def test_descarta_legs_de_baja_probabilidad(self):
        """Una leg de 30% no entra aunque tenga edge: el pedido es
        'buena probabilidad de darse', no 'máximo premio'."""
        picks = [
            _pick("A @ B", "Bueno Uno", 80.0, 1.45),
            _pick("C @ D", "Bueno Dos", 75.0, 1.50),
            _pick("E @ F", "Flojo", 30.0, 4.50, market="batter_home_runs"),
        ]
        combos = _combos(picks)
        assert combos
        jugadores = {leg.player for c in combos for leg in c.legs}
        assert "Flojo" not in jugadores

    def test_todas_las_combinadas_tienen_ev_positivo(self):
        picks = [
            _pick("A @ B", "Uno", 80.0, 1.45),
            _pick("C @ D", "Dos", 75.0, 1.50),
            _pick("E @ F", "Tres", 70.0, 1.60),
        ]
        for combo in _combos(picks):
            assert combo.expected_value_pct > 0

    def test_respeta_el_piso_de_probabilidad_del_combo(self):
        picks = [
            _pick("A @ B", "Uno", 80.0, 1.45),
            _pick("C @ D", "Dos", 75.0, 1.50),
            _pick("E @ F", "Tres", 70.0, 1.60),
        ]
        for combo in _combos(picks, min_prob_combo=50.0):
            assert combo.combined_probability_pct >= 50.0

    def test_sin_legs_suficientes_no_inventa_combinadas(self):
        """Con una sola leg buena no hay combo posible: devolver algo
        sería forzar una recomendación."""
        assert _combos([_pick("A @ B", "Solo", 80.0, 1.45)]) == []

    def test_sin_picks_devuelve_vacio(self):
        assert _combos([]) == []


class TestCorrelacion:
    def test_marca_las_combinadas_del_mismo_partido(self):
        """Multiplicar probabilidades asume independencia; dentro del
        mismo partido eso no se cumple y hay que avisarlo."""
        picks = [
            _pick("Yankees @ Red Sox", "Judge", 80.0, 1.45),
            _pick("Yankees @ Red Sox", "Soto", 75.0, 1.50),
        ]
        combos = _combos(picks)
        assert combos
        assert all(c.same_game for c in combos)

    def test_prioriza_partidos_distintos(self):
        picks = [
            _pick("Yankees @ Red Sox", "Judge", 80.0, 1.45),
            _pick("Yankees @ Red Sox", "Soto", 78.0, 1.48),
            _pick("Dodgers @ Padres", "Betts", 75.0, 1.50),
        ]
        combos = _combos(picks)
        assert combos
        assert not combos[0].same_game

    def test_no_repite_jugador_en_un_combo(self):
        picks = [
            _pick("A @ B", "Judge", 80.0, 1.45, market="batter_hits"),
            _pick("A @ B", "Judge", 70.0, 1.60, market="batter_runs_scored"),
            _pick("C @ D", "Betts", 75.0, 1.50),
        ]
        for combo in _combos(picks):
            nombres = [leg.player for leg in combo.legs]
            assert len(nombres) == len(set(nombres))


class TestMatematica:
    def test_probabilidad_combinada_es_el_producto(self):
        picks = [
            _pick("A @ B", "Uno", 80.0, 1.45),
            _pick("C @ D", "Dos", 75.0, 1.50),
        ]
        combo = _combos(picks)[0]
        # El producto crudo sería 60.0 (0.80 * 0.75), pero se aplica un
        # descuento por dependencia: las legs no son independientes
        # -comparten día y condiciones- y multiplicar como si lo fueran
        # sobreestima. Con 2 legs de partidos distintos: 60 * 0.97.
        assert combo.combined_probability_pct == 58.2

    def test_cuota_combinada_es_el_producto(self):
        picks = [
            _pick("A @ B", "Uno", 80.0, 1.45),
            _pick("C @ D", "Dos", 75.0, 1.50),
        ]
        combo = _combos(picks)[0]
        assert combo.combined_odds == round(1.45 * 1.50, 2)


class TestSonadoras:
    """Una soñadora es improbable por definición. Lo que sí se exige es
    que llegue a la cuota pedida, que mantenga valor positivo, y que sea
    la de mayor probabilidad disponible en ese rango."""

    def _picks_variados(self):
        return [
            _pick("Yankees @ Sox", "Judge", 80.0, 1.45),
            _pick("Dodgers @ Padres", "Betts", 75.0, 1.50),
            _pick("Mets @ Braves", "Wheeler", 65.0, 1.80, market="pitcher_strikeouts"),
            _pick("Cubs @ Cards", "Suzuki", 60.0, 2.00),
            _pick("Astros @ Rangers", "Alvarez", 52.0, 2.40, market="batter_home_runs"),
            _pick("Giants @ Rockies", "Chapman", 45.0, 2.90, market="batter_home_runs"),
        ]

    def _dream(self, picks, **kwargs):
        from app.analysis.combos import find_dream_combos

        with patch("app.analysis.combos.find_daily_picks", return_value=picks):
            return find_dream_combos(**kwargs)

    def test_todas_llegan_a_la_cuota_pedida(self):
        for combo in self._dream(self._picks_variados(), min_odds=10.0):
            assert combo.combined_odds >= 10.0

    def test_mantiene_valor_esperado_positivo(self):
        """Subir la cuota no habilita meter legs sin valor."""
        for combo in self._dream(self._picks_variados(), min_odds=10.0):
            assert combo.expected_value_pct > 0

    def test_ordenadas_por_probabilidad_descendente(self):
        combos = self._dream(self._picks_variados(), min_odds=10.0)
        probs = [c.combined_probability_pct for c in combos]
        assert probs == sorted(probs, reverse=True)

    def test_usa_mas_legs_que_las_conservadoras(self):
        combos = self._dream(self._picks_variados(), min_odds=10.0)
        assert combos
        assert all(c.size >= 3 for c in combos)

    def test_sin_cuota_alcanzable_no_inventa(self):
        """Si con las legs disponibles no se llega a la cuota pedida, se
        devuelve vacío en vez de ofrecer una de cuota menor haciéndola
        pasar por soñadora."""
        assert self._dream(self._picks_variados(), min_odds=500.0) == []

    def test_llega_a_cuotas_muy_altas_usando_mas_legs(self):
        """Con 6 legs sí se puede llegar a 50x: no debe descartarlas."""
        combos = self._dream(self._picks_variados(), min_odds=50.0)
        assert combos
        assert combos[0].combined_odds >= 50.0


class TestSonadoras:
    """Una soñadora tiene probabilidad baja por definición. Lo que
    verificamos no es que sea probable, sino que sea defendible: cuota
    alta, muchas legs, y valor esperado positivo en todas."""

    def _picks_cuota_alta(self):
        return [
            _pick("Yanks @ Sox", "Judge", 45.0, 2.60, market="batter_home_runs"),
            _pick("Dodgers @ Padres", "Betts", 50.0, 2.30),
            _pick("Mets @ Braves", "Wheeler", 40.0, 3.00, market="pitcher_strikeouts"),
            _pick("Cubs @ Cards", "Suzuki", 42.0, 2.80),
            _pick("Rays @ Jays", "Franco", 55.0, 2.10),
        ]

    def _dream(self, picks, **kwargs):
        from app.analysis.combos import find_dream_combos

        with patch("app.analysis.combos.find_daily_picks", return_value=picks):
            return find_dream_combos(**kwargs)

    def test_alcanza_cuota_alta(self):
        for combo in self._dream(self._picks_cuota_alta()):
            assert combo.combined_odds >= 8.0

    def test_usa_varias_legs(self):
        for combo in self._dream(self._picks_cuota_alta()):
            assert combo.size >= 4

    def test_igual_exige_valor_positivo(self):
        """Lo que la hace defendible: aunque sea improbable, cada leg
        aporta ventaja en vez de diluirla."""
        for combo in self._dream(self._picks_cuota_alta()):
            assert combo.expected_value_pct > 0

    def test_no_repite_jugador(self):
        for combo in self._dream(self._picks_cuota_alta()):
            nombres = [leg.player for leg in combo.legs]
            assert len(nombres) == len(set(nombres))

    def test_sin_legs_suficientes_no_inventa(self):
        picks = [_pick("A @ B", "Uno", 45.0, 2.60), _pick("C @ D", "Dos", 50.0, 2.30)]
        assert self._dream(picks) == []

    def test_ordena_por_probabilidad_entre_sonadoras(self):
        combos = self._dream(self._picks_cuota_alta())
        if len(combos) > 1:
            probs = [c.combined_probability_pct for c in combos if not c.same_game]
            assert probs == sorted(probs, reverse=True)


class TestNombresDeEquipo:
    """El usuario no conoce las abreviaturas (NYY, LAD), así que se usan
    los apodos: son únicos en MLB, se reconocen sin saber la ciudad y
    ocupan bastante menos que el nombre completo."""

    def test_saca_la_ciudad(self):
        from app.utils.equipos import nombre_corto

        assert nombre_corto("New York Yankees") == "Yankees"
        assert nombre_corto("Atlanta Braves") == "Braves"

    def test_apodos_de_dos_palabras(self):
        from app.utils.equipos import nombre_corto

        assert nombre_corto("Boston Red Sox") == "Red Sox"
        assert nombre_corto("Chicago White Sox") == "White Sox"
        assert nombre_corto("Toronto Blue Jays") == "Blue Jays"

    def test_no_confunde_equipos_de_la_misma_ciudad(self):
        from app.utils.equipos import nombre_corto

        assert nombre_corto("New York Yankees") != nombre_corto("New York Mets")
        assert nombre_corto("Los Angeles Angels") != nombre_corto("Los Angeles Dodgers")
        assert nombre_corto("Chicago Cubs") != nombre_corto("Chicago White Sox")

    def test_partido_completo(self):
        from app.utils.equipos import partido_corto

        assert partido_corto("New York Yankees @ Boston Red Sox") == "Yankees @ Red Sox"

    def test_acepta_separadores_distintos(self):
        from app.utils.equipos import partido_corto

        assert partido_corto("Texas Rangers - Seattle Mariners") == "Rangers @ Mariners"

    def test_sin_dato_no_rompe(self):
        from app.utils.equipos import nombre_corto, partido_corto

        assert nombre_corto(None) == "?"
        assert partido_corto(None) == "?"
