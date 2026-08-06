"""Generador de combinadas con valor.

Idea central: una combinada NO tiene valor por ser combinada. Solo lo
tiene si cada leg por separado ya lo tiene. Combinar una leg con valor
negativo arrastra a todo el combo, aunque las otras sean buenas.

Por eso acá partimos de los picks que ya pasaron el filtro de valor
(probabilidad real del jugador > probabilidad implícita en la cuota) y
recién sobre esos armamos combinaciones.

Sobre la independencia: multiplicar probabilidades asume que las legs
no están correlacionadas. Eso es razonable si son de PARTIDOS DISTINTOS,
y falso dentro del mismo partido (si un equipo se desata, varios de sus
bateadores conectan a la vez). Por eso priorizamos combos de partidos
distintos y avisamos cuando no lo son.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

from app.analysis.daily_picks import DailyPick, find_daily_picks
from app.utils.logger import get_logger

log = get_logger(__name__)

# Cada leg tiene que ser sólida por sí sola: de nada sirve un combo de
# tiros al aire aunque la cuota sea alta.
_MIN_PROB_POR_LEG = 55.0
# Piso de probabilidad del combo completo: si baja de acá, deja de ser
# "buena probabilidad de darse" y pasa a ser una lotería.
_MIN_PROB_COMBO = 25.0


@dataclass
class ComboLeg:
    match: str
    player: str
    market: str
    line: str
    odds: float
    probability_pct: float
    sample_size: int
    commence_time: str | None = None


@dataclass
class ValueCombo:
    legs: list[ComboLeg]
    combined_probability_pct: float
    combined_odds: float
    expected_value_pct: float
    same_game: bool

    @property
    def size(self) -> int:
        return len(self.legs)


def _to_leg(pick: DailyPick) -> ComboLeg:
    return ComboLeg(
        match=pick.match,
        player=pick.player,
        market=pick.market,
        line=pick.line,
        odds=pick.odds,
        probability_pct=pick.our_probability_pct,
        sample_size=pick.sample_size,
        commence_time=pick.commence_time,
    )


def _build_combo(legs: tuple[ComboLeg, ...]) -> ValueCombo:
    prob = 1.0
    odds = 1.0
    for leg in legs:
        prob *= leg.probability_pct / 100
        odds *= leg.odds

    partidos = {leg.match for leg in legs}
    same_game = len(partidos) == 1

    # Penalización por dependencia. Multiplicar probabilidades supone que
    # las legs son INDEPENDIENTES, y no lo son: comparten día, clima y
    # rival, y si son del mismo partido comparten hasta el pitcher que
    # enfrentan. Cuantas más legs, más se acumula el error: el producto
    # crudo sobreestima siempre, y cada vez más.
    #
    # No hay una corrección exacta sin datos históricos propios -para eso
    # está /calibracion-. Mientras tanto se aplica un descuento explícito
    # y conservador, más fuerte cuando las legs son del mismo partido.
    factor = 0.93 if same_game else 0.97
    prob *= factor ** max(0, len(legs) - 1)

    # El EV se calcula con la probabilidad YA corregida: calcularlo con la
    # inflada mostraría valor donde no lo hay.
    ev = (prob * odds - 1) * 100

    return ValueCombo(
        legs=list(legs),
        combined_probability_pct=round(prob * 100, 1),
        combined_odds=round(odds, 2),
        expected_value_pct=round(ev, 1),
        same_game=len(partidos) < len(legs),
    )


def find_value_combos(
    max_legs: int = 3,
    max_results: int = 4,
    min_prob_combo: float = _MIN_PROB_COMBO,
    max_events: int = 5,
    min_prob_leg: float = _MIN_PROB_POR_LEG,
    min_legs: int = 2,
    min_odds: float = 0.0,
    max_pool: int = 8,
) -> list[ValueCombo]:
    """Arma combinadas de 2 y 3 legs a partir de picks con valor.

    Devuelve las mejores ordenadas por probabilidad de darse (no por
    cuota): el pedido es "buena probabilidad", no "máximo premio".
    """
    picks = find_daily_picks(max_events=max_events)
    solidos = [_to_leg(p) for p in picks if p.our_probability_pct >= min_prob_leg]

    if len(solidos) < min_legs:
        return []

    # Nos quedamos con los mejores para no explotar en combinaciones
    solidos = sorted(solidos, key=lambda l: l.probability_pct, reverse=True)[:max_pool]

    combos: list[ValueCombo] = []
    for size in range(min_legs, max_legs + 1):
        for grupo in combinations(solidos, size):
            # Un mismo jugador no puede aparecer dos veces en el combo
            if len({leg.player for leg in grupo}) < len(grupo):
                continue
            combo = _build_combo(grupo)
            if combo.combined_probability_pct < min_prob_combo:
                continue
            if combo.expected_value_pct <= 0:
                continue  # sin valor esperado positivo no lo ofrecemos
            if combo.combined_odds < min_odds:
                continue
            combos.append(combo)

    # Orden: primero los de partidos distintos (donde la multiplicación
    # de probabilidades es defendible), después por probabilidad.
    combos.sort(key=lambda c: (c.same_game, -c.combined_probability_pct))
    return combos[:max_results]


# --- Soñadoras -------------------------------------------------------

# --- Soñadoras -----------------------------------------------------------
#
# Una soñadora es una combinada larga de cuota alta. Por definición tiene
# probabilidad baja: no existe "cuota 20 con 60% de chance", sería un error
# de la casa que se corrige en segundos.
#
# Lo que SÍ podemos garantizar es que sea defendible: que cada leg tenga
# valor propio. Ahí pasa algo interesante — si cada leg tiene edge, el edge
# se multiplica. Cinco legs con +10% cada una dan (1.10^5 - 1) = +61% de
# valor esperado. La soñadora tiene MÁS valor esperado que una simple; lo
# que sube muchísimo es la varianza.
#
# Por eso acá bajamos el piso de probabilidad por leg (los mercados que
# pagan alto son inherentemente menos probables) pero NO negociamos el
# requisito de valor positivo.

_MIN_PROB_LEG_SONADORA = 30.0
_MIN_CUOTA_SONADORA = 8.0


@dataclass
class DreamCombo(ValueCombo):
    """Igual que una ValueCombo pero pensada para cuota alta."""


def find_dream_combos(
    min_legs: int = 4,
    max_legs: int = 6,
    max_results: int = 3,
    min_odds: float = _MIN_CUOTA_SONADORA,
    max_events: int = 12,
) -> list[ValueCombo]:
    """Arma soñadoras: combinadas largas de cuota alta, pero SOLO con
    legs que tienen valor esperado positivo por separado.

    Ordena por probabilidad descendente: entre dos soñadoras de cuota
    parecida, preferimos la que más chance tiene de darse.
    """
    picks = find_daily_picks(max_events=max_events)
    candidatas = [
        _to_leg(p) for p in picks if p.our_probability_pct >= _MIN_PROB_LEG_SONADORA
    ]

    if len(candidatas) < min_legs:
        return []

    # Priorizamos por edge (valor), no por probabilidad: en una soñadora
    # lo que buscamos es acumular ventaja, no seguridad.
    candidatas = sorted(
        picks, key=lambda p: p.edge_pct, reverse=True
    )
    candidatas = [
        _to_leg(p) for p in candidatas if p.our_probability_pct >= _MIN_PROB_LEG_SONADORA
    ][:14]  # pool más grande: con 9 apenas alcanzaba para combinar

    combos: list[ValueCombo] = []
    for size in range(min_legs, max_legs + 1):
        for grupo in combinations(candidatas, size):
            if len({leg.player for leg in grupo}) < len(grupo):
                continue
            combo = _build_combo(grupo)
            if combo.combined_odds < min_odds:
                continue
            if combo.expected_value_pct <= 0:
                continue
            combos.append(combo)

    if not combos:
        return []

    # Entre soñadoras, la mejor es la que más probabilidad tiene de darse
    combos.sort(key=lambda c: (c.same_game, -c.combined_probability_pct))
    return combos[:max_results]
