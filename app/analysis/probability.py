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
    sugerencia: str | None = None  # otra línea del mismo mercado que rinde más


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
    # Estos dos ya estaban en la tabla de nombres de Stake pero nunca acá:
    # como ahora la web muestra el nombre de Stake, ese texto vuelve a
    # entrar por este clasificador y hay que reconocerlo.
    if "total base" in m or "bases totales" in m:
        return ["total_bases"]
    if "single" in m or "simple" in m:
        return ["singles"]
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
    # "Salidas del Campo" es como Stake llama a los outs. Faltaba, y como
    # ahora mostramos el nombre de Stake en la web, ese texto volvía a
    # entrar acá y no se reconocía: "Mercado de pitcheo no reconocido".
    if "out" in m and "strikeout" not in m:
        return ["outs"]
    if "salida" in m:
        return ["outs"]
    if "walk" in m or "caminata" in m or "base por bola" in m or "boleto" in m:
        return ["walks"]
    # Estos dos ya estaban en la tabla de nombres de Stake pero nunca acá:
    # como ahora la web muestra el nombre de Stake, ese texto vuelve a
    # entrar por este clasificador y hay que reconocerlo.
    if "total base" in m or "bases totales" in m:
        return ["total_bases"]
    if "single" in m or "simple" in m:
        return ["singles"]
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


def _cargar_jugador_y_partidos(
    player_name: str, market_text: str, line_text: str, sample: int = _DEFAULT_SAMPLE
) -> tuple[dict, str, float, bool, list[str], list[dict]]:
    """Busca al jugador y sus últimos partidos para el mercado pedido.

    Compartido por estimate_leg_probability y estimate_leg_detail para
    no repetir la misma búsqueda dos veces (y no terminar con dos
    versiones de la misma lógica pisándose, como ya pasó antes)."""
    if not player_name or not line_text:
        raise ProbabilityError("Falta jugador o línea para poder estimar probabilidad.")

    player = search_player(player_name)
    if not player or not player.get("id"):
        raise ProbabilityError(f"No encontré a '{player_name}' en el roster actual de MLB.")

    side, threshold = _parse_line(line_text)
    is_pitcher = player.get("position") == "Pitcher"

    if is_pitcher:
        stat_fields = _classify_pitcher_market(market_text)
        games = get_recent_pitching_games(player["id"], last_n=sample)
    else:
        stat_fields = _classify_batter_market(market_text)
        games = get_recent_hitting_games(player["id"], last_n=sample)

    if not games:
        raise ProbabilityError(
            f"No hay partidos recientes registrados para {player['full_name']} esta temporada."
        )

    return player, side, threshold, is_pitcher, stat_fields, games


# Piso de probabilidad para sugerir otra línea. Por debajo de esto ya no
# es "una apuesta mejor", es otra apuesta más arriesgada.
_PISO_SUGERENCIA = 70.0


def _sugerir_linea(
    valores: list[float], side: str, threshold: float, probabilidad_actual: float
) -> str | None:
    """Busca si había una línea MÁS EXIGENTE del mismo mercado que igual
    entraba seguido.

    Ejemplo real: alguien apostó "Hits Allowed Over 3.5" y el pitcher
    promedia 6.3 -- pegó 90% de las veces, pero pagaba poco justamente
    porque era fácil. Si "Over 5.5" también entraba el 80% de las veces,
    esa era la apuesta: misma confianza, mucha mejor cuota.

    Solo sugiere si la línea alternativa sigue por encima de
    _PISO_SUGERENCIA; si no, estaríamos empujando a arriesgar más sin
    respaldo. Devuelve None cuando la línea elegida ya era la correcta.
    """
    if not valores or probabilidad_actual < _PISO_SUGERENCIA:
        # Si la apuesta original ya es floja, sugerir algo MÁS exigente
        # sería empeorarla.
        return None

    # Candidatas: líneas .5 entre la actual y el máximo observado.
    piso, techo = int(min(valores)), int(max(valores))
    if side == "Over":
        candidatas = [x + 0.5 for x in range(int(threshold), techo + 1)]
        candidatas = [c for c in candidatas if c > threshold]
    else:
        candidatas = [x + 0.5 for x in range(piso, int(threshold) + 1)]
        candidatas = [c for c in candidatas if c < threshold]

    mejor = None
    for c in candidatas:
        aciertos = (
            sum(1 for v in valores if v > c) if side == "Over"
            else sum(1 for v in valores if v < c)
        )
        pct = aciertos / len(valores) * 100
        if pct >= _PISO_SUGERENCIA:
            mejor = (c, round(pct, 1))

    if not mejor:
        return None
    linea, pct = mejor
    return f"{side} {linea:g} también entraba en {pct:g}%"


def estimate_leg_probability(player_name: str, market_text: str, line_text: str) -> LegEstimate:
    player, side, threshold, is_pitcher, stat_fields, games = _cargar_jugador_y_partidos(
        player_name, market_text, line_text
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
        sugerencia=_sugerir_linea(values, side, threshold, probability_pct),
    )


@dataclass
class GameLogEntry:
    date: str | None
    value: float
    hit: bool  # si ESE partido cumplió la línea


@dataclass
class LegDetail:
    """Igual que LegEstimate pero con el desglose partido por partido,
    para cuando el usuario pide profundizar en un jugador puntual en
    vez de quedarse con el resumen ('90% en sus últimos 10')."""
    player: str
    market: str
    side: str
    threshold: float
    probability_pct: float
    avg_value: float
    is_pitcher: bool
    games: list[GameLogEntry]


def estimate_leg_detail(player_name: str, market_text: str, line_text: str) -> LegDetail:
    player, side, threshold, is_pitcher, stat_fields, games = _cargar_jugador_y_partidos(
        player_name, market_text, line_text
    )

    entries = []
    for g in games:
        valor = sum(g.get(f, 0) for f in stat_fields)
        cumplio = valor > threshold if side == "Over" else valor < threshold
        entries.append(GameLogEntry(date=g.get("date"), value=valor, hit=cumplio))

    hits_condition = sum(1 for e in entries if e.hit)
    probability_pct = round(hits_condition / len(entries) * 100, 1) if entries else 0.0
    avg_value = round(sum(e.value for e in entries) / len(entries), 2) if entries else 0.0

    return LegDetail(
        player=player["full_name"],
        market=market_text,
        side=side,
        threshold=threshold,
        probability_pct=probability_pct,
        avg_value=avg_value,
        is_pitcher=is_pitcher,
        games=entries,
    )


@dataclass
class Sugerencia:
    """Una línea alternativa para el MISMO jugador y mercado."""
    linea: float
    side: str
    probabilidad_pct: float
    es_la_apostada: bool


def sugerir_lineas(
    player_name: str, market_text: str, line_text: str, sample: int = _DEFAULT_SAMPLE
) -> list[Sugerencia]:
    """Calcula qué habría pasado con OTRAS líneas del mismo mercado.

    Es la pregunta que uno se hace mirando una apuesta: "¿me convenía
    pedir más?". Si un pitcher promedia 6.3 hits permitidos y apostaste
    Over 3.5, seguramente podías ir a Over 4.5 o 5.5 -misma seguridad,
    bastante mejor cuota-.

    Ojo con qué es y qué no: esto es frecuencia histórica sobre los
    últimos partidos, la misma base que el resto del bot. Sirve para ver
    si la línea que tomaste estaba floja respecto de lo que el jugador
    viene haciendo, NO para prometer que va a pasar.
    """
    _player, side, threshold, _is_pitcher, stat_fields, games = _cargar_jugador_y_partidos(
        player_name, market_text, line_text, sample
    )

    valores = [sum(g.get(f, 0) for f in stat_fields) for g in games]
    if not valores:
        return []

    def _pct(limite: float) -> float:
        if side == "Over":
            aciertos = sum(1 for v in valores if v > limite)
        else:
            aciertos = sum(1 for v in valores if v < limite)
        return round(aciertos / len(valores) * 100, 1)

    # Candidatas: medios puntos alrededor de lo que el jugador viene
    # haciendo. Se acotan al rango observado para no listar líneas
    # absurdas que ninguna casa va a ofrecer.
    tope = max(valores)
    candidatas = [x + 0.5 for x in range(0, int(tope) + 1)]
    if threshold not in candidatas:
        candidatas.append(threshold)

    return sorted(
        (
            Sugerencia(
                linea=c,
                side=side,
                probabilidad_pct=_pct(c),
                es_la_apostada=abs(c - threshold) < 0.01,
            )
            for c in candidatas
        ),
        key=lambda s: s.linea,
    )


def mejor_alternativa(sugerencias: list[Sugerencia], minimo_pct: float = 80.0) -> Sugerencia | None:
    """De las alternativas, la MÁS exigente que igual mantiene una
    probabilidad alta -o sea, la que paga más sin resignar seguridad.

    Devuelve None si la línea apostada ya era la mejor: no tiene sentido
    sugerir algo peor que lo que la persona ya eligió.
    """
    apostada = next((s for s in sugerencias if s.es_la_apostada), None)
    if not apostada:
        return None

    if apostada.side == "Over":
        # Subir la línea paga más; queremos la más alta que siga siendo segura.
        mejores = [
            s for s in sugerencias
            if s.linea > apostada.linea and s.probabilidad_pct >= minimo_pct
        ]
        return max(mejores, key=lambda s: s.linea) if mejores else None

    mejores = [
        s for s in sugerencias
        if s.linea < apostada.linea and s.probabilidad_pct >= minimo_pct
    ]
    return min(mejores, key=lambda s: s.linea) if mejores else None
