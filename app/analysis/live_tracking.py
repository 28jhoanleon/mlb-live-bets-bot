"""Tracking en vivo: mira el boxscore del partido EN CURSO y estima,
para cada leg:
  - cuánto lleva hecho esta noche (progreso real, no promedio)
  - la probabilidad de llegar a la línea con lo que queda de partido
  - una barra visual de progreso
  - si el jugador parece seguir activo en el partido

Sobre la probabilidad "hacia adelante": no inventamos una certeza que
no tenemos. Usamos el promedio reciente del jugador (últimos 10
partidos / 5 starts) proyectado sobre la fracción de partido que
queda, con una distribución de Poisson — el modelo estándar para
conteos raros (hits, ponches, outs) en un intervalo de tiempo. Es una
aproximación razonable, no una certeza matemática.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from app.analysis.probability import (
    ProbabilityError,
    _classify_batter_market,
    _classify_pitcher_market,
    _normalize,
    _parse_line,
)
from app.mlb.estados import TERMINADO as _TERMINADO
from app.mlb.live import find_live_game_by_teams, get_live_boxscore, get_live_game
from app.mlb.pitchers import get_recent_pitching_games
from app.mlb.players import get_recent_hitting_games, search_player
from app.utils.progress_bar import build_progress_bar
from app.utils.logger import get_logger

log = get_logger(__name__)

_TOTAL_HALF_INNINGS = 18  # 9 innings x 2 (visitante/local)


@dataclass
class LiveLegStatus:
    player: str
    market: str
    side: str
    threshold: float
    current_value: float
    already_hit: bool
    # True solo si el partido terminó y la leg no se cumplió: resultado
    # definitivo, distinto de "va perdiendo pero todavía puede darse".
    perdida: bool
    forward_probability_pct: float | None  # None si ya se cumplió o no hay datos
    progress_bar: str
    active_status: str  # texto tipo "🟢 en el partido" / "🔴 salió" / "❓ sin confirmar"
    status_text: str


def _split_match(match_text: str) -> tuple[str, str]:
    for sep in (" vs ", " @ ", " - "):
        if sep in match_text:
            a, b = match_text.split(sep, 1)
            return a.strip(), b.strip()
    return match_text.strip(), ""


def find_live_game_for_leg(match_text: str) -> int | None:
    away_hint, home_hint = _split_match(match_text)
    if not away_hint:
        return None
    return find_live_game_by_teams(away_hint, home_hint)


def _remaining_fraction(inning: int | None, inning_state: str | None) -> float:
    """Qué fracción del partido queda, en base al inning actual.
    Aproximado: no descuenta outs dentro del inning en curso."""
    if not inning:
        return 0.5  # sin dato, asumimos mitad de partido como default conservador
    completed_half_innings = (inning - 1) * 2 + (1 if inning_state == "Bottom" else 0)
    remaining = 1 - (completed_half_innings / _TOTAL_HALF_INNINGS)
    return max(0.0, min(1.0, remaining))


def _poisson_prob_over(needed: float, lam: float) -> float:
    """P(X >= ceil(needed)) con X ~ Poisson(lam). needed puede ser
    fraccionario (ej. necesita superar 4.5 -> hace falta al menos 5)."""
    if lam <= 0:
        return 0.0
    k = math.ceil(needed)
    cdf = sum((lam**i) * math.exp(-lam) / math.factorial(i) for i in range(k))
    return round((1 - cdf) * 100, 1)


def _poisson_prob_under(allowed: float, lam: float) -> float:
    """P(X <= floor(allowed)) con X ~ Poisson(lam)."""
    if lam <= 0:
        return 100.0
    k = math.floor(allowed)
    if k < 0:
        return 0.0
    cdf = sum((lam**i) * math.exp(-lam) / math.factorial(i) for i in range(k + 1))
    return round(cdf * 100, 1)


def _recent_avg_rate(player_id: int, fields: list[str], is_pitcher: bool) -> float:
    games = (
        get_recent_pitching_games(player_id, last_n=5)
        if is_pitcher
        else get_recent_hitting_games(player_id, last_n=10)
    )
    if not games:
        return 0.0
    total = sum(sum(g.get(f, 0) for f in fields) for g in games)
    return total / len(games)


def _fmt_num(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)


def _check_active_status(
    player_name: str,
    player_stats: dict,
    is_pitcher: bool,
    current_pitcher: str | None,
) -> str:
    """Determina si el jugador sigue participando.

    Para pitchers usamos la lista de pitchers de SU equipo: el último de
    esa lista es el que está lanzando por ese equipo. No sirve comparar
    contra "el pitcher que lanza en este momento", porque cuando el
    equipo del jugador está bateando, ese pitcher es el del rival — y
    daríamos por sustituido a alguien que sigue en el partido.
    """
    if is_pitcher:
        outs_lanzados = player_stats.get("pitching", {}).get("outs", 0)
        es_ultimo_de_su_equipo = player_stats.get("is_team_last_pitcher")

        if es_ultimo_de_su_equipo is True:
            if player_stats.get("is_current_pitcher"):
                return "🟢 lanzando ahora mismo"
            return "🟢 sigue siendo el pitcher de su equipo (su equipo está bateando)"

        if es_ultimo_de_su_equipo is False and outs_lanzados > 0:
            return "🔴 ya salió del partido (su equipo cambió de pitcher)"

        if outs_lanzados == 0:
            return "❓ todavía no lanzó en este partido"

        return "❓ no pude confirmar su estado"

    # Bateador. Ojo con `isOnBench`: la API lo pone en true para cualquier
    # jugador que no esté bateando EN ESE INSTANTE, incluidos los titulares
    # mientras su equipo defiende. Usarlo solo daba falsos "está en el
    # banco" y pintaba de rojo legs con 80% de probabilidad.
    #
    # Por eso el orden de bateo manda: si tiene uno asignado, es titular.
    if player_stats.get("is_current_batter"):
        return "🟢 bateando ahora mismo"
    if player_stats.get("batting_order") is not None:
        return "🟢 en el line-up"
    if player_stats.get("is_on_bench"):
        # Sin orden de bateo y en el banco: suplente que todavía no entró.
        # No lo damos por perdido; todavía puede entrar.
        return "❓ suplente, todavía no entró al partido"
    return "❓ no pude confirmar — revisá el line-up en la casa de apuestas"


def track_leg_live(leg: dict, boxscore: dict, live_state: dict) -> LiveLegStatus:
    player_name = leg.get("player")
    if not player_name:
        raise ProbabilityError("Sin jugador identificado.")

    player_stats = boxscore.get(player_name)
    resolved_name = player_name
    if not player_stats:
        # La IA lee la captura y suele perder tildes ("Arraez" en vez de
        # "Arráez"), pero la MLB Stats API sí las conserva en fullName.
        # Sin normalizar esto, una leg de un partido EN VIVO caía al
        # fallback histórico solo porque no encontrábamos al jugador.
        buscado = _normalize(player_name)
        for name, stats in boxscore.items():
            candidato = _normalize(name)
            if buscado in candidato or candidato in buscado:
                player_stats = stats
                resolved_name = name
                break

    if not player_stats:
        raise ProbabilityError(f"No encontré a {leg.get('player')} en el boxscore de este partido.")

    side, threshold = _parse_line(leg.get("line", ""))

    player_info = search_player(resolved_name)
    is_pitcher = bool(player_info and player_info.get("position") == "Pitcher")

    if is_pitcher:
        fields = _classify_pitcher_market(leg.get("market", ""))
        current_value = sum(player_stats.get("pitching", {}).get(f, 0) for f in fields)
    else:
        fields = _classify_batter_market(leg.get("market", ""))
        current_value = sum(player_stats.get("batting", {}).get(f, 0) for f in fields)

    # Un Over queda ASEGURADO apenas se supera la línea: las estadísticas
    # solo suben, no puede revertirse.
    #
    # Un Under NO funciona así: estar por debajo a mitad de partido no
    # significa nada, el jugador puede superar la línea en cualquier
    # momento. Solo se resuelve cuando el partido termina. Marcarlo como
    # cumplido antes sería mentir: mostraría ✅ desde el primer lanzamiento.
    partido_terminado = str(live_state.get("status") or "") in _TERMINADO
    if side == "Over":
        already_hit = current_value > threshold
    else:
        already_hit = current_value < threshold and partido_terminado

    active_status = _check_active_status(
        resolved_name, player_stats, is_pitcher, live_state.get("current_pitcher")
    )

    forward_pct = None
    if already_hit:
        status_text = "ASEGURADA — ya no puede revertirse" if side == "Over" else "CUMPLIDA"
        emoji = "✅"
    elif partido_terminado:
        # Partido terminado y no se cumplió: la leg está PERDIDA, no
        # "improbable". Conservamos el resultado final en vez de volver al
        # promedio histórico, que borraría cómo quedó el ticket.
        status_text = f"NO SE DIO — quedó en {_fmt_num(current_value)}"
        emoji = "❌"
    elif is_pitcher and "🔴" in active_status:
        # Si el pitcher ya salió y no cumplió, la leg está prácticamente decidida en contra
        status_text = "ya no sigue en el montículo — improbable que se cumpla"
        emoji = "🔴"
    else:
        remaining_fraction = _remaining_fraction(live_state.get("inning"), live_state.get("inning_state"))
        player_id = player_info.get("id") if player_info else None
        avg_rate = _recent_avg_rate(player_id, fields, is_pitcher) if player_id else 0.0
        projected_lambda = avg_rate * remaining_fraction

        if side == "Over":
            needed = threshold - current_value
            forward_pct = _poisson_prob_over(needed, projected_lambda)
            status_text = f"{forward_pct}% de llegar con lo que resta de partido"
        else:
            allowed = threshold - current_value
            forward_pct = _poisson_prob_under(allowed, projected_lambda)
            status_text = f"va {_fmt_num(current_value)}, {forward_pct}% de mantenerse bajo {_fmt_num(threshold)}"
        emoji = "🟡"

    perdida = bool(partido_terminado and not already_hit)

    if already_hit:
        bar_state = "done"
    elif perdida:
        bar_state = "lost"
    elif is_pitcher and "🔴" in active_status:
        bar_state = "dead"
    else:
        bar_state = "pending"

    progress_bar = build_progress_bar(
        current_value,
        threshold,
        side=side,
        already_hit=already_hit,
        show_check=True,
        state=bar_state,
    )

    return LiveLegStatus(
        player=resolved_name,
        market=leg.get("market", ""),
        side=side,
        threshold=threshold,
        current_value=current_value,
        already_hit=already_hit,
        perdida=perdida,
        forward_probability_pct=forward_pct,
        progress_bar=progress_bar,
        active_status=active_status,
        status_text=status_text,
    )


def get_live_tracking_for_match(match_text: str) -> tuple[dict, dict] | None:
    """Busca el partido en vivo y devuelve (boxscore, live_state), o
    None si el partido no está en curso ahora mismo."""
    game_pk = find_live_game_for_leg(match_text)
    if not game_pk:
        return None
    boxscore = get_live_boxscore(game_pk)
    live_state = get_live_game(game_pk)
    return boxscore, live_state
