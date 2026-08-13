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

import time
from concurrent.futures import ThreadPoolExecutor

from app.analysis.probability import (
    ProbabilityError,
    estimate_leg_probability,
    limpiar_cache_estimaciones,
    precalentar_cache,
)
from app.analysis.value import implied_probability
from app.utils.logger import get_logger
from app.utils.tiempo import evento_vigente, formato_hora_fecha

log = get_logger(__name__)

# Edge mínimo para considerar un pick. Antes 8.0, que sumado a pedir sólo
# 3 mercados dejaba el pool casi vacío y las soñadoras nunca salían.
# 5.0 sigue exigiendo ventaja real sobre la cuota, pero deja pasar
# suficientes candidatas para poder combinar.
_MIN_EDGE_FOR_PICK = 5.0


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


# Tiempo máximo que puede tardar un barrido. Si se pasa, devuelve lo que
# haya juntado hasta ahí en vez de seguir indefinidamente: es preferible
# una respuesta parcial a un comando que se queda colgado sin decir nada.
PRESUPUESTO_SEGUNDOS = 90


def find_daily_picks(
    max_events: int = 12,
    min_edge_pct: float = _MIN_EDGE_FOR_PICK,
    presupuesto_segundos: float = PRESUPUESTO_SEGUNDOS,
) -> list[DailyPick]:
    """Recorre los props del día, calcula nuestra propia probabilidad
    (últimos partidos reales) para cada uno, y la compara contra lo que
    implica la cuota de mercado. Devuelve los picks con mayor edge."""
    from app.odds import parlay
    from app.odds.theodds import (  # import local: evita ciclo
        OddsClientError,
        get_events,
        get_player_props,
        partidos_que_alcanzan,
    )

    arranque = time.monotonic()

    def _sin_tiempo() -> bool:
        return time.monotonic() - arranque > presupuesto_segundos

    limpiar_cache_estimaciones()

    props_por_evento: list[tuple[dict, dict | None]] = []

    # ParlayAPI primero: trae TODOS los mercados de TODOS los partidos en
    # una sola llamada de 3 créditos. Con The Odds API había que pedir
    # partido por partido -12 créditos por barrido-, que es lo que nos
    # dejó la cuota en negativo. Si falla, se cae al proveedor viejo: no
    # queremos depender de un servicio nuevo sin red de contención.
    if parlay.hay_clave():
        try:
            agrupados = parlay.props_por_evento()
            for datos in agrupados.values():
                if evento_vigente(datos["event"].get("commence_time")):
                    props_por_evento.append((datos["event"], datos["props"]))
            log.info("ParlayAPI: %d partidos con props", len(props_por_evento))
        except parlay.ParlayClientError:
            log.warning("ParlayAPI falló, uso The Odds API", exc_info=True)

    if not props_por_evento:
        try:
            events = get_events()
        except OddsClientError:
            return []

        # Descartamos partidos ya terminados o de días anteriores.
        events = [e for e in events if evento_vigente(e.get("commence_time"))]

        permitidos = partidos_que_alcanzan(max_events)
        if permitidos == 0:
            log.warning("Sin cuota en The Odds API: no hago el barrido")
            return []
        if permitidos < max_events:
            log.info("Cuota justa: reviso %d partidos en vez de %d", permitidos, max_events)

        def _props(event):
            try:
                return event, get_player_props(event["id"])
            except OddsClientError:
                return event, None

        with ThreadPoolExecutor(max_workers=6) as ex:
            props_por_evento = list(ex.map(_props, events[:permitidos]))

    # Ahora que sabemos qué jugadores aparecen, se traen todos de una en
    # paralelo. Después el bucle no toca la red: son aciertos de caché.
    nombres = [
        o.get("description")
        for _, data in props_por_evento if data
        for b in data.get("bookmakers", [])
        for m in b.get("markets", [])
        for o in m.get("outcomes", [])
    ]
    precalentar_cache(nombres)

    picks: list[DailyPick] = []
    for event, props_data in props_por_evento:
        if not props_data:
            continue
        if _sin_tiempo():
            log.warning(
                "Corté el barrido por tiempo (%.0fs): devuelvo %d picks",
                presupuesto_segundos, len(picks),
            )
            break

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

                    # Defensa: una cuota de 2.00 exacta en un mercado
                    # muy probable (o muy improbable) casi siempre es un
                    # precio de relleno, no una oportunidad. Sin esto, un
                    # marcador que se filtre genera picks fantasma con
                    # ventajas de cuatro cifras.
                    if abs(price - 2.0) < 0.001:
                        continue

                    try:
                        estimate = estimate_leg_probability(player, market_label, line_text)
                    except ProbabilityError:
                        continue
                    except Exception:
                        # Un corte de red o un rate-limit de la MLB API en UN
                        # prop no puede tumbar el barrido entero: antes
                        # burbujeaba hasta el handler y /sonadoras terminaba
                        # con "error inesperado" sin resultado alguno.
                        log.warning("Fallo estimando %s (%s), sigo con el resto",
                                    player, market_label, exc_info=True)
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
