"""Estima la probabilidad de un pick individual (leg) usando la
frecuencia empírica de los últimos N partidos reales del jugador, en
vez de asumir una distribución teórica (Poisson, normal, etc).

Filosofía: "en sus últimos 10 partidos, superó esta línea en X de 10"
es más directo, más verificable y más alineado a un enfoque sniper que
un modelo con supuestos que el usuario no puede auditar a simple vista.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from app.mlb.pitchers import get_recent_pitching_games
from app.mlb.players import get_recent_hitting_games, search_player
from app.utils.logger import get_logger

log = get_logger(__name__)

_DEFAULT_SAMPLE = 10


class ProbabilityError(Exception):
    """No se pudo estimar probabilidad (jugador no encontrado, sin
    datos suficientes, o mercado no reconocido)."""


@dataclass
class LegEstimate:
    player: str
    market: str
    side: str  # "Over" | "Under"
    threshold: float
    probability_pct: float
    sample_size: int
    avg_value: float
    is_pitcher: bool


def _normalize(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()


def _parse_line(line_text: str) -> tuple[str, float]:
    """'Over 6.5' / 'Sobre 3.5' / 'Más de 2.5' -> ('Over', valor).

    Las casas de apuestas en español usan varias formas para lo mismo
    ('Sobre', 'Más de', 'Arriba de', 'Encima de'), y la IA devuelve la
    línea tal como la ve en la captura. Cubrimos ese vocabulario en vez
    de fallar.

    Si aparece un número pero ninguna palabra de dirección, preferimos
    fallar antes que adivinar: confundir un Under con un Over daría una
    probabilidad exactamente al revés.
    """
    normalized = _normalize(line_text)

    under_words = ("under", "menos", "bajo", "debajo", "abajo", "inferior")
    over_words = ("over", "mas", "sobre", "arriba", "encima", "superior")

    pattern = r"\b(" + "|".join(under_words + over_words) + r")\b\s*(?:de\s*)?([\d]+(?:[.,][\d]+)?)"
    m = re.search(pattern, normalized)

    if not m:
        # Puede venir como "O 3.5" / "U 3.5" (abreviado en algunas casas)
        m_abbr = re.search(r"\b([ou])\s*([\d]+(?:[.,][\d]+)?)", normalized)
        if m_abbr:
            side = "Under" if m_abbr.group(1) == "u" else "Over"
            return side, float(m_abbr.group(2).replace(",", "."))
        raise ProbabilityError(f"No pude interpretar la línea '{line_text}'")

    word = m.group(1)
    side = "Under" if word in under_words else "Over"
    return side, float(m.group(2).replace(",", "."))


def _classify_batter_market(market_text: str) -> list[str]:
    """Mapea el nombre del mercado a los campos del game log.

    Soporta inglés y español (Stake/Betano en español usan 'Golpes' por
    hits, 'Caminatas' por walks, 'Carreras Remolcadas' por RBIs, etc).

    ORDEN IMPORTANTE: los mercados combinados (H+R+RBI) van PRIMERO.
    Si se evalúan después, un texto como 'Golpes + Carreras + Carreras
    Remolcadas' matchea con 'carrera' y devuelve solo runs — contando de
    menos y dando una probabilidad equivocada.
    """
    m = _normalize(market_text)

    # --- Combinados primero ---
    has_hits = "hit" in m or "golpe" in m
    has_runs = "run" in m or "carrera" in m
    has_rbi = "rbi" in m or "remolcada" in m or "impulsada" in m
    if (has_hits and has_runs and has_rbi) or "h+r+rbi" in m:
        return ["hits", "runs", "rbi"]

    # --- Individuales ---
    if "home run" in m or "jonron" in m or re.search(r"\bhr\b", m):
        return ["home_runs"]
    if "robada" in m or "stolen" in m:
        return ["stolen_bases"]
    if has_rbi:
        return ["rbi"]
    if "strikeout" in m or "ponche" in m:
        return ["strikeouts"]
    if "walk" in m or "caminata" in m or "base por bola" in m or "boleto" in m:
        return ["walks"]
    if has_hits:
        return ["hits"]
    if has_runs and "home" not in m:
        return ["runs"]
    raise ProbabilityError(f"Mercado de bateo no reconocido: '{market_text}'")


def _classify_pitcher_market(market_text: str) -> list[str]:
    """Igual que el de bateo, pero para stats de pitcheo.

    Ojo con 'Golpes Permitidos' / 'Hits Allowed': es un mercado de
    pitcher, no de bateador.
    """
    m = _normalize(market_text)

    if "ponche" in m or "strikeout" in m or m.strip() == "k":
        return ["strikeouts"]
    if "out" in m and "strikeout" not in m:
        return ["outs"]
    if "walk" in m or "caminata" in m or "base por bola" in m or "boleto" in m:
        return ["walks"]
    if (
        "earned run" in m
        or "carrera limpia" in m
        or "carrera permitida" in m
        or "carrera conseguida" in m
        or "carreras conseguidas" in m
        or "runs allowed" in m
        or "runs conceded" in m
    ):
        return ["earned_runs"]
    if "hit" in m or "golpe" in m:
        return ["hits_allowed"]
    # 'Runs' a secas en una prop de pitcher son las carreras que PERMITE.
    # Sin esta línea, mercados como "Runs Over 1.5" quedaban sin reconocer.
    if "carrera" in m or "run" in m:
        return ["earned_runs"]
    raise ProbabilityError(f"Mercado de pitcheo no reconocido: '{market_text}'")


def estimate_leg_probability(player_name: str, market_text: str, line_text: str) -> LegEstimate:
    if not player_name or not line_text:
        raise ProbabilityError("Falta jugador o línea para poder estimar probabilidad.")

    player = search_player(player_name)
    if not player or not player.get("id"):
        raise ProbabilityError(f"No encontré a '{player_name}' en el roster actual de MLB.")

    side, threshold = _parse_line(line_text)
    is_pitcher = player.get("position") == "Pitcher"

    if is_pitcher:
        stat_fields = _classify_pitcher_market(market_text)
        games = get_recent_pitching_games(player["id"], last_n=_DEFAULT_SAMPLE)
    else:
        stat_fields = _classify_batter_market(market_text)
        games = get_recent_hitting_games(player["id"], last_n=_DEFAULT_SAMPLE)

    if not games:
        raise ProbabilityError(
            f"No hay partidos recientes registrados para {player['full_name']} esta temporada."
        )

    values = [sum(g.get(f, 0) for f in stat_fields) for g in games]
    hits_condition = (
        sum(1 for v in values if v > threshold)
        if side == "Over"
        else sum(1 for v in values if v < threshold)
    )
    probability_pct = round(hits_condition / len(values) * 100, 1)
    avg_value = round(sum(values) / len(values), 2)

    return LegEstimate(
        player=player["full_name"],
        market=market_text,
        side=side,
        threshold=threshold,
        probability_pct=probability_pct,
        sample_size=len(values),
        avg_value=avg_value,
        is_pitcher=is_pitcher,
    )
