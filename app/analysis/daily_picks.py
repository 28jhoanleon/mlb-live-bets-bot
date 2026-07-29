"""Picks automáticos del día: cruza probabilidad histórica real del
jugador con la cuota de mercado, para encontrar props donde el mercado
está mal pricing (probabilidad real > probabilidad implícita por la cuota).

A diferencia de /value (que solo compara casas entre sí), esto usa
nuestro propio modelo estadístico como ancla de "probabilidad justa" —
más parecido a lo que pedía el brief original: un analista, no un
comparador de cuotas nomás.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.analysis.probability import ProbabilityError, estimate_leg_probability
from app.analysis.value import implied_probability
from app.utils.logger import get_logger
from app.utils.tiempo import evento_vigente, formato_hora_fecha

log = get_logger(__name__)

_MIN_EDGE_FOR_PICK = 8.0  # más exigente que /value: acá la "probabilidad justa" es nuestra propia estimación, no consenso de mercado


@dataclass
class DailyPick:
    match: str
    player: str
    market: str
    line: str
    odds: float
    our_probability_pct: float
    market_probability_pct: float
    edge_pct: float
    sample_size: int
    # Horario del partido (ISO UTC). Se muestra convertido a hora local
    # para saber cuándo hay que tener puesta la apuesta.
    commence_time: str | None = None


def confidence_stars(edge_pct: float) -> str:
    if edge_pct >= 20:
        return "⭐⭐⭐⭐⭐"
    if edge_pct >= 15:
        return "⭐⭐⭐⭐"
    if edge_pct >= 10:
        return "⭐⭐⭐"
    return "⭐⭐"


def find_daily_picks(max_events: int = 5, min_edge_pct: float = _MIN_EDGE_FOR_PICK) -> list[DailyPick]:
    """Recorre los props del día, calcula nuestra propia probabilidad
    (últimos partidos reales) para cada uno, y la compara contra lo que
    implica la cuota de mercado. Devuelve los picks con mayor edge."""
    from app.odds.theodds import OddsClientError, get_events, get_player_props  # import local: evita ciclo

    try:
        events = get_events()
    except OddsClientError:
        return []

    # Descartamos partidos ya terminados o de días anteriores: sugerir un
    # pick de un juego que ya se jugó no sirve para nada, y The Odds API
    # a veces devuelve eventos viejos todavía en la lista.
    events = [e for e in events if evento_vigente(e.get("commence_time"))]

    picks: list[DailyPick] = []
    for event in events[:max_events]:
        try:
            props_data = get_player_props(event["id"])
        except OddsClientError:
            continue

        match_name = f"{event.get('away_team', '?')} @ {event.get('home_team', '?')}"
        hora_evento = event.get("commence_time")

        for book in props_data.get("bookmakers", []):
            for market in book.get("markets", []):
                for outcome in market.get("outcomes", []):
                    player = outcome.get("description")
                    point = outcome.get("point")
                    side = outcome.get("name")
                    price = outcome.get("price")
                    if not player or point is None or price is None or side != "Over":
                        continue  # nos quedamos con el lado Over para simplificar el ranking

                    market_label = market.get("key", "")
                    line_text = f"Over {point}"

                    try:
                        estimate = estimate_leg_probability(player, market_label, line_text)
                    except ProbabilityError:
                        continue

                    market_prob = implied_probability(float(price)) * 100
                    edge = estimate.probability_pct - market_prob
                    if edge < min_edge_pct:
                        continue

                    picks.append(
                        DailyPick(
                            match=match_name,
                            player=player,
                            market=market_label,
                            line=line_text,
                            odds=float(price),
                            our_probability_pct=estimate.probability_pct,
                            market_probability_pct=round(market_prob, 1),
                            edge_pct=round(edge, 1),
                            sample_size=estimate.sample_size,
                            commence_time=hora_evento,
                        )
                    )

    picks.sort(key=lambda p: p.edge_pct, reverse=True)
    # Evitar mostrar el mismo jugador/mercado repetido de varias casas
    seen = set()
    unique_picks = []
    for p in picks:
        dedup_key = (p.player, p.market, p.line)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        unique_picks.append(p)
    return unique_picks
