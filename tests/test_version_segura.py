"""Versión SEGURA de una combinada: lo opuesto a una soñadora.

No busca cuota alta. Conserva los jugadores y mercados que eligió el
usuario y BAJA las líneas hasta que cada tramo sea muy probable. Se
resigna cuota para que la apuesta entre.
"""
from unittest.mock import patch

from app.analysis.auditoria import OBJETIVO_SEGURO, version_segura
from app.analysis.probability import Sugerencia


def _opciones(pares, apostada):
    return [
        Sugerencia(linea=l, side="Over", probabilidad_pct=p,
                   es_la_apostada=(l == apostada))
        for l, p in pares
    ]


class TestBajaLasLineas:
    def test_baja_hasta_alcanzar_el_objetivo(self):
        ops = _opciones([(0.5, 95.0), (1.5, 74.0), (2.5, 45.0)], apostada=1.5)
        with patch("app.analysis.probability.sugerir_lineas", return_value=ops):
            tramos, _ = version_segura(
                [{"player": "X", "market": "batter_hits", "line": "Over 1.5"}]
            )
        assert tramos[0].linea_nueva == "Over 0.5"
        assert tramos[0].probabilidad >= OBJETIVO_SEGURO
        assert tramos[0].cambio is True

    def test_no_baja_de_mas(self):
        """Si una línea más exigente YA alcanza el objetivo, se queda con
        ésa: bajar de más regala cuota sin ganar seguridad."""
        ops = _opciones([(0.5, 99.0), (1.5, 94.0), (2.5, 91.0), (3.5, 60.0)],
                        apostada=0.5)
        with patch("app.analysis.probability.sugerir_lineas", return_value=ops):
            tramos, _ = version_segura(
                [{"player": "X", "market": "batter_hits", "line": "Over 0.5"}]
            )
        assert tramos[0].linea_nueva == "Over 2.5"

    def test_si_ya_estaba_bien_no_marca_cambio(self):
        ops = _opciones([(0.5, 95.0), (1.5, 60.0)], apostada=0.5)
        with patch("app.analysis.probability.sugerir_lineas", return_value=ops):
            tramos, _ = version_segura(
                [{"player": "X", "market": "batter_hits", "line": "Over 0.5"}]
            )
        assert tramos[0].cambio is False

    def test_si_ninguna_llega_devuelve_la_mejor(self):
        """Mejor informar la más probable que omitir el tramo callado."""
        ops = _opciones([(0.5, 70.0), (1.5, 40.0)], apostada=1.5)
        with patch("app.analysis.probability.sugerir_lineas", return_value=ops):
            tramos, _ = version_segura(
                [{"player": "X", "market": "batter_hits", "line": "Over 1.5"}]
            )
        assert tramos[0].probabilidad == 70.0


class TestProbabilidadCombinada:
    def test_multiplicar_tramos_baja_el_total(self):
        """Cuatro tramos al 95% NO dan 95%. Decirlo evita vender una
        seguridad que no existe."""
        ops = _opciones([(0.5, 95.0)], apostada=0.5)
        with patch("app.analysis.probability.sugerir_lineas", return_value=ops):
            _, combinada = version_segura([
                {"player": f"J{i}", "market": "batter_hits", "line": "Over 0.5"}
                for i in range(4)
            ])
        assert combinada < 95.0
        assert combinada < 85.0, "no aplicó la penalización por dependencia"

    def test_un_solo_tramo_no_se_penaliza(self):
        ops = _opciones([(0.5, 95.0)], apostada=0.5)
        with patch("app.analysis.probability.sugerir_lineas", return_value=ops):
            _, combinada = version_segura(
                [{"player": "X", "market": "batter_hits", "line": "Over 0.5"}]
            )
        assert combinada == 95.0


class TestCasosLimite:
    def test_sin_legs_no_explota(self):
        assert version_segura([]) == ([], None)

    def test_una_leg_sin_jugador_se_saltea(self):
        assert version_segura([{"market": "x", "line": "Over 0.5"}]) == ([], None)

    def test_si_falla_el_calculo_sigue_con_el_resto(self):
        def _lado(jugador, m, l):
            if jugador == "Explota":
                raise ConnectionError("cortó")
            return _opciones([(0.5, 95.0)], apostada=0.5)

        with patch("app.analysis.probability.sugerir_lineas", side_effect=_lado):
            tramos, _ = version_segura([
                {"player": "Bueno", "market": "batter_hits", "line": "Over 0.5"},
                {"player": "Explota", "market": "batter_hits", "line": "Over 0.5"},
            ])
        assert [t.player for t in tramos] == ["Bueno"]


class TestUmbral:
    def test_el_umbral_esta_en_85(self):
        """Elegido con la cuenta a la vista: con 80% una combinada de 4
        entra el 37% de las veces (no es "segura"); con 90% entra el 60%
        pero paga 1.52x y no compensa. 85% da 48% pagando 1.92x."""
        assert OBJETIVO_SEGURO == 85.0


class TestTramosQueNoLlegan:
    """Se marcan con ❌ en vez de descartarse en silencio: saber CUÁL es
    el tramo que arruina la combinada es la información útil."""

    def test_marca_el_que_no_alcanza(self):
        ops = _opciones([(0.5, 72.0), (1.5, 44.0)], apostada=1.5)
        with patch("app.analysis.probability.sugerir_lineas", return_value=ops):
            tramos, _ = version_segura(
                [{"player": "X", "market": "batter_hits", "line": "Over 1.5"}]
            )
        assert tramos[0].no_alcanza is True

    def test_no_marca_el_que_si_llega(self):
        ops = _opciones([(0.5, 95.0)], apostada=0.5)
        with patch("app.analysis.probability.sugerir_lineas", return_value=ops):
            tramos, _ = version_segura(
                [{"player": "X", "market": "batter_hits", "line": "Over 0.5"}]
            )
        assert tramos[0].no_alcanza is False

    def test_la_combinada_ignora_los_descartados(self):
        """La probabilidad tiene que ser la de la apuesta RECOMENDADA,
        no la de una que incluye tramos que ya dijimos que saque."""
        def _lado(jugador, m, l):
            if jugador == "Malo":
                return _opciones([(0.5, 50.0)], apostada=0.5)
            return _opciones([(0.5, 95.0)], apostada=0.5)

        with patch("app.analysis.probability.sugerir_lineas", side_effect=_lado):
            tramos, combinada = version_segura([
                {"player": "Bueno1", "market": "batter_hits", "line": "Over 0.5"},
                {"player": "Bueno2", "market": "batter_hits", "line": "Over 0.5"},
                {"player": "Malo", "market": "batter_hits", "line": "Over 0.5"},
            ])

        # Solo los dos buenos: 0.95 * 0.95 * 0.97
        assert combinada is not None and combinada > 85.0
        assert len([t for t in tramos if t.no_alcanza]) == 1

    def test_si_ninguno_llega_no_hay_combinada(self):
        ops = _opciones([(0.5, 40.0)], apostada=0.5)
        with patch("app.analysis.probability.sugerir_lineas", return_value=ops):
            tramos, combinada = version_segura([
                {"player": "X", "market": "batter_hits", "line": "Over 0.5"},
            ])
        assert combinada is None
        assert tramos[0].no_alcanza is True
