"""value.py no tenía ningún test. El motivo para escribirlos ahora: el
bug real era justamente que `remove_vig` existía, tenía docstring y
todo, pero `find_value_bets` nunca la llamaba -- promediaba
probabilidades implícitas CON el margen de cada casa adentro. Sin un
test que ejercite el devig de verdad, ese tipo de bug puede volver a
colarse sin que ninguna suite lo note."""
from app.analysis.value import (
    ValueBet,
    find_value_bets,
    group_props_by_outcome,
    implied_probability,
    remove_vig,
)


class TestImpliedProbability:
    def test_cuota_2_00_es_50_por_ciento(self):
        assert implied_probability(2.00) == 0.5

    def test_cuota_invalida_da_cero(self):
        assert implied_probability(1.0) == 0.0
        assert implied_probability(0.5) == 0.0


class TestRemoveVig:
    def test_normaliza_a_que_sumen_1(self):
        # 0.55 + 0.50 = 1.05 -> 5% de vig
        fair = remove_vig([0.55, 0.50])
        assert round(sum(fair), 6) == 1.0
        assert fair[0] > fair[1]  # el orden relativo se mantiene

    def test_lista_vacia_o_con_ceros_no_explota(self):
        assert remove_vig([0.0, 0.0]) == [0.0, 0.0]


class TestFindValueBetsDevigReal:
    """El caso que importa: una casa con margen bajo en un lado (línea
    generosa) tiene que aparecer con valor real, calculado sacándole el
    margen a CADA casa por separado antes de promediar -- no
    promediando probabilidades con el margen todavía adentro."""

    def _libros_parejos(self, generosa: dict[str, float]) -> dict[str, dict[str, float]]:
        # Tres casas "normales" con ~5% de margen parejo en las dos puntas,
        # más una casa con una línea inusualmente generosa del lado Over.
        normal = {"Over": 1.905, "Under": 1.905}  # implica 0.525 + 0.525 = 1.05
        return {
            "CasaA": dict(normal),
            "CasaB": dict(normal),
            "CasaC": dict(normal),
            "CasaGenerosa": generosa,
        }

    def test_detecta_valor_en_la_casa_con_margen_bajo(self):
        libros = self._libros_parejos({"Over": 2.20, "Under": 1.85})
        bets = find_value_bets(libros, min_edge_pct=3.0)

        casa_generosa = [b for b in bets if b.book == "CasaGenerosa" and b.side == "Over"]
        assert casa_generosa, f"no detectó la casa con línea generosa: {bets}"
        # Número exacto del devig real: si alguien saca remove_vig y vuelve
        # a promediar probabilidades crudas (el bug viejo), este edge da
        # 11.6% en vez de 7.6% -- un simple "apareció o no apareció" no
        # hubiera notado la diferencia.
        assert casa_generosa[0].fair_probability == 48.9
        assert casa_generosa[0].edge_pct == 7.6

    def test_no_marca_valor_falso_en_casas_parejas(self):
        """Las tres casas normales, idénticas entre sí, no tienen edge
        real entre ellas -- no deberían aparecer como value bet."""
        libros = self._libros_parejos({"Over": 2.20, "Under": 1.85})
        bets = find_value_bets(libros, min_edge_pct=3.0)

        normales = [b for b in bets if b.book in ("CasaA", "CasaB", "CasaC")]
        assert normales == [], f"marcó valor falso en casas sin edge real: {normales}"

    def test_una_sola_casa_con_las_dos_puntas_nunca_da_valor_positivo(self):
        """Devigar una casa contra sí misma solo puede devolver su propio
        margen (negativo), nunca valor a favor -- si esto diera positivo
        sería un bug (estaría inventando valor de la nada)."""
        libros = {"UnicaCasa": {"Over": 1.905, "Under": 1.905}}
        bets = find_value_bets(libros, min_edge_pct=0.01)
        assert bets == []

    def test_sin_ninguna_casa_con_las_dos_puntas_no_explota(self):
        """Respaldo: si ninguna casa publicó Over Y Under, no se puede
        devigar de verdad -- no debe reventar, solo no encontrar nada
        raro (usa el promedio crudo como antes, sin inventar edge)."""
        libros = {"CasaA": {"Over": 1.90}, "CasaB": {"Over": 1.95}}
        bets = find_value_bets(libros, min_edge_pct=3.0)
        assert isinstance(bets, list)  # no explota


class TestGroupPropsByOutcome:
    def test_agrupa_por_mercado_conservando_el_par_por_casa(self):
        payload = {
            "bookmakers": [
                {
                    "title": "Stake",
                    "markets": [
                        {
                            "key": "batter_hits",
                            "outcomes": [
                                {"description": "Aaron Judge", "name": "Over", "point": 0.5, "price": 1.90},
                                {"description": "Aaron Judge", "name": "Under", "point": 0.5, "price": 1.95},
                            ],
                        }
                    ],
                }
            ]
        }
        grouped = group_props_by_outcome(payload)
        clave = "batter_hits|Aaron Judge|0.5"
        assert clave in grouped
        assert grouped[clave]["Stake"] == {"Over": 1.90, "Under": 1.95}
