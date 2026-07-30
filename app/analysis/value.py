"""Detección de valor esperado (+EV) cruzando cuotas de distintas casas.

Método: "devigging" por consenso. Cada casa tiene margen (vig) metido en
sus cuotas. Si promediamos las probabilidades implícitas de varias casas
y les sacamos el margen, obtenemos una estimación razonable de la
probabilidad "real" del mercado. Después buscamos si ALGUNA casa ofrece
una cuota mejor a esa probabilidad real -> ahí hay valor.

Esto es un proxy estadístico, no un modelo propio de jugadores/pitchers.
Sirve como primera capa de +EV; el análisis fino con stats de pitchers/
bateadores (K%, xFIP, etc.) se suma después en analysis/props.py.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ValueBet:
    book: str
    side: str
    price: float
    fair_probability: float
    implied_probability: float
    edge_pct: float


def implied_probability(decimal_odds: float) -> float:
    """Probabilidad implícita de una cuota decimal, sin ajustar por vig."""
    if decimal_odds <= 1.0:
        return 0.0
    return 1.0 / decimal_odds


def remove_vig(probabilities: list[float]) -> list[float]:
    """Normaliza probabilidades implícitas para que sumen 1.0 (sin vig).

    Ej: dos outcomes con probabilidades implícitas 0.55 y 0.50 (suman 1.05,
    5% de vig) se normalizan a 0.524 y 0.476.
    """
    total = sum(probabilities)
    if total == 0:
        return probabilities
    return [p / total for p in probabilities]


def find_value_bets(
    book_sides: dict[str, dict[str, float]],
    min_edge_pct: float = 3.0,
) -> list[ValueBet]:
    """Dado un mismo outcome (ej. 'Woo K') cotizado por varias casas,
    calcula la probabilidad justa por consenso y devuelve las casas que
    ofrecen valor por encima de `min_edge_pct`.

    book_sides: {nombre_casa: {"Over": cuota, "Under": cuota}} para EL
    MISMO mercado específico (mismo jugador, misma línea). No hace
    falta que todas las casas tengan las dos puntas.

    El devig es POR CASA: cada casa mete su propio margen en sus dos
    puntas, así que hay que sacárselo casa por casa (remove_vig sobre
    el par Over/Under de ESA casa) antes de promediar entre casas. Antes
    esto promediaba directamente las probabilidades implícitas crudas
    -con el margen de cada casa todavía adentro- lo que infla la
    "probabilidad justa" y hace ver valor donde en realidad es margen.
    """
    fair_por_lado: dict[str, list[float]] = {}
    for cuotas in book_sides.values():
        over, under = cuotas.get("Over"), cuotas.get("Under")
        if over is None or under is None:
            continue  # sin las dos puntas de ESTA casa no se puede devigar
        fair_over, fair_under = remove_vig(
            [implied_probability(over), implied_probability(under)]
        )
        fair_por_lado.setdefault("Over", []).append(fair_over)
        fair_por_lado.setdefault("Under", []).append(fair_under)

    fair_prob_por_lado: dict[str, float] = {}
    if fair_por_lado:
        for lado, valores in fair_por_lado.items():
            fair_prob_por_lado[lado] = sum(valores) / len(valores)
    else:
        # Ninguna casa publicó las dos puntas: no se puede devigar de
        # verdad. Como respaldo, promediamos las implícitas crudas (el
        # comportamiento viejo) en vez de no dar ninguna estimación.
        crudas: dict[str, list[float]] = {}
        for cuotas in book_sides.values():
            for lado, precio in cuotas.items():
                crudas.setdefault(lado, []).append(implied_probability(precio))
        fair_prob_por_lado = {
            lado: sum(vs) / len(vs) for lado, vs in crudas.items()
        }

    value_bets = []
    for book, cuotas in book_sides.items():
        for lado, price in cuotas.items():
            fair_prob = fair_prob_por_lado.get(lado)
            if fair_prob is None:
                continue
            implied = implied_probability(price)
            edge = (fair_prob - implied) / implied * 100 if implied > 0 else 0
            if edge >= min_edge_pct:
                value_bets.append(
                    ValueBet(
                        book=book,
                        side=lado,
                        price=price,
                        fair_probability=round(fair_prob * 100, 1),
                        implied_probability=round(implied * 100, 1),
                        edge_pct=round(edge, 1),
                    )
                )
    return sorted(value_bets, key=lambda v: v.edge_pct, reverse=True)


def group_props_by_outcome(props_data: dict) -> dict[str, dict[str, dict[str, float]]]:
    """Reorganiza la respuesta cruda de The Odds API agrupando por
    mercado único (jugador + mercado + línea), con las cuotas de cada
    casa separadas por lado (Over/Under). Conservar el par por casa es
    lo que permite devigar cada casa por separado en find_value_bets."""
    grouped: dict[str, dict[str, dict[str, float]]] = {}
    for book in props_data.get("bookmakers", []):
        book_name = book.get("title", "?")
        for market in book.get("markets", []):
            market_key = market.get("key", "")
            for outcome in market.get("outcomes", []):
                player = outcome.get("description", outcome.get("name", "?"))
                point = outcome.get("point")
                side = outcome.get("name", "")
                price = outcome.get("price")
                if price is None:
                    continue
                key = f"{market_key}|{player}|{point}"
                grouped.setdefault(key, {}).setdefault(book_name, {})[side] = float(price)
    return grouped


def matches_preferred(book_name: str, preferred: list[str]) -> bool:
    """Compara de forma laxa: 'bet365' matchea 'Bet365 AU', 'stake'
    matchea 'Stake.com', etc."""
    if not preferred:
        return True
    normalizado = book_name.lower().replace(".", "").replace(" ", "")
    return any(p.replace(".", "").replace(" ", "") in normalizado for p in preferred)


def scan_value_bets(
    min_edge_pct: float = 3.0,
    max_events: int = 5,
    preferred_books: list[str] | None = None,
) -> list[tuple[dict, str, "ValueBet"]]:
    """Escanea los próximos partidos y devuelve las value bets encontradas.

    IMPORTANTE sobre `preferred_books`: filtra qué apuestas se DEVUELVEN,
    no con qué casas se calcula la probabilidad justa. El consenso se
    sigue armando con todas las casas disponibles — si lo calculáramos
    con solo dos, un 'edge' significaría apenas que una casa difiere de
    la otra, no que haya valor real.

    Compartido entre /value y el job de alertas automáticas.
    """
    from app.odds.theodds import OddsClientError, get_events, get_player_props  # import local: evita ciclo odds<->analysis

    try:
        events = get_events()
    except OddsClientError:
        return []

    preferred = [p.lower() for p in (preferred_books or [])]

    all_bets: list[tuple[dict, str, ValueBet]] = []
    for event in events[:max_events]:
        try:
            props_data = get_player_props(event["id"])
        except OddsClientError:
            continue
        # El consenso se calcula con TODAS las casas del payload...
        grouped = group_props_by_outcome(props_data)
        for key, book_sides in grouped.items():
            for bet in find_value_bets(book_sides, min_edge_pct=min_edge_pct):
                # ...y recién acá filtramos por dónde podés jugarla.
                if matches_preferred(bet.book, preferred):
                    all_bets.append((event, key, bet))

    all_bets.sort(key=lambda x: x[2].edge_pct, reverse=True)
    return all_bets
