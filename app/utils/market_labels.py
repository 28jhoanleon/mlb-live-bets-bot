"""Etiquetas de mercado.

Dos formas de nombrar lo mismo:

- `market_label`: nombre corto para listados internos.
- `nombre_stake`: cómo lo muestra Stake en español, que es lo que el
  usuario tiene que buscar en la app para encontrar la apuesta. De poco
  sirve decir "Hits" si en la pantalla dice "Golpes".

Vive en utils y no en un handler porque lo usan los comandos y el job de
alertas: dejarlo en un handler ya rompió una vez.
"""
from app.utils.telegram_helpers import escape_md

MARKET_LABELS = {
    "pitcher_strikeouts": "🎯 Ponches",
    "batter_hits": "⚾ Hits",
    "batter_home_runs": "💥 Home Runs",
    "batter_rbis": "🏃 RBIs",
    "batter_runs_scored": "🏃 Carreras",
    "pitcher_outs": "⚾ Outs",
    "batter_walks": "🚶 Caminatas",
    "batter_stolen_bases": "💨 Bases robadas",
    "batter_strikeouts": "🎯 Ponches del bateador",
    "batter_hits_runs_rbis": "⚾ Golpes + Carreras + Carreras Remolcadas",
    "pitcher_hits_allowed": "⚾ Golpes Permitidos",
    "pitcher_earned_runs": "🏃 Carreras Limpias",
}

# Exactamente como aparece en Stake, para que se pueda buscar ahí.
# Copiado de la pantalla de mercados del jugador: Stake mezcla inglés y
# español ("Hits", pero "Salidas del Campo"), así que se respeta tal
# cual en vez de traducir todo.
NOMBRES_STAKE = {
    # Bateo
    "batter_hits": "Hits",
    "batter_home_runs": "Home Runs",
    "batter_rbis": "RBIs",
    "batter_runs_scored": "Carreras",
    "batter_total_bases": "Bases Totales",
    "batter_singles": "Simples",
    "batter_walks": "Bases por bolas del bateador (batter walks)",
    "batter_strikeouts": "Ponches (strikeouts) del bateador",
    "batter_stolen_bases": "Bases Robadas",
    "batter_hits_runs_rbis": "Golpes + Carreras + Carreras Remolcadas (RBIs)",
    # Pitcheo
    "pitcher_strikeouts": "Strikeouts",
    "pitcher_outs": "Salidas del Campo",
    "pitcher_earned_runs": "Carreras Conseguidas",
    "pitcher_hits_allowed": "Golpes Permitidos",
    "pitcher_walks": "Caminatas",
}


def nombre_stake_texto(market_text: str, is_pitcher: bool | None = None) -> str:
    """Traduce CUALQUIER forma de nombrar un mercado al nombre exacto de
    Stake.

    Hace falta porque el nombre llega de tres lados distintos: claves
    técnicas de The Odds API (`batter_hits`), texto que la IA leyó de una
    captura en inglés ("Hits Allowed") y texto en español ("Golpes
    Permitidos"). Antes solo se traducían las claves técnicas, así que la
    web mostraba "Hits Allowed" mientras Stake decía "Golpes Permitidos"
    y no había forma de encontrar la apuesta.

    is_pitcher desambigua los mercados que existen para los dos roles:
    "Strikeouts" de un pitcher son los que reparte; los de un bateador,
    los que se come.
    """
    if not market_text:
        return ""
    if market_text in NOMBRES_STAKE:
        return NOMBRES_STAKE[market_text]

    from app.analysis.probability import _normalize

    m = _normalize(market_text)

    # Combinado primero: contiene las palabras de los tres individuales.
    tiene_hits = "hit" in m or "golpe" in m
    tiene_runs = "run" in m or "carrera" in m
    tiene_rbi = "rbi" in m or "remolcada" in m or "impulsada" in m
    if (tiene_hits and tiene_runs and tiene_rbi) or "h+r+rbi" in m:
        return NOMBRES_STAKE["batter_hits_runs_rbis"]

    permitidos = "allowed" in m or "permitido" in m
    if permitidos and tiene_hits:
        return NOMBRES_STAKE["pitcher_hits_allowed"]

    # "out" tiene que ir antes que el resto, pero cuidando de no
    # confundirlo con "strikeout", que lo contiene como substring.
    if "out" in m and "strikeout" not in m and "ponche" not in m:
        return NOMBRES_STAKE["pitcher_outs"]

    if "strikeout" in m or "ponche" in m:
        return NOMBRES_STAKE["batter_strikeouts" if is_pitcher is False else "pitcher_strikeouts"]

    if "earned run" in m or "carrera limpia" in m or "carrera conseguida" in m:
        return NOMBRES_STAKE["pitcher_earned_runs"]

    if "walk" in m or "caminata" in m or "base por bola" in m or "boleto" in m:
        return NOMBRES_STAKE["pitcher_walks" if is_pitcher else "batter_walks"]

    if "total base" in m or "bases totales" in m:
        return NOMBRES_STAKE["batter_total_bases"]
    if "single" in m or "simple" in m:
        return NOMBRES_STAKE["batter_singles"]
    if "home run" in m or "jonron" in m:
        return NOMBRES_STAKE["batter_home_runs"]
    if "robada" in m or "stolen" in m:
        return NOMBRES_STAKE["batter_stolen_bases"]
    if tiene_rbi:
        return NOMBRES_STAKE["batter_rbis"]
    if tiene_hits:
        return NOMBRES_STAKE["pitcher_hits_allowed" if is_pitcher else "batter_hits"]
    if tiene_runs:
        return NOMBRES_STAKE["pitcher_earned_runs" if is_pitcher else "batter_runs_scored"]

    return market_text


def market_label(market_key: str) -> str:
    return MARKET_LABELS.get(market_key, market_key.replace("_", " ").title())


def nombre_stake(market_key: str) -> str:
    """Cómo buscar ese mercado dentro de la app de Stake.

    Si la clave no está en la tabla puede venir de dos lugares: una clave
    técnica de The Odds API (`batter_hits_runs_rbis`) o un nombre que ya
    leyó la IA de una captura ("Hits + Runs + RBIs"). Solo hay que
    embellecer el primer caso: aplicarle `.title()` al segundo lo
    arruinaba ("RBIs" -> "Rbis").
    """
    if market_key in NOMBRES_STAKE:
        return NOMBRES_STAKE[market_key]
    if "_" in market_key or market_key.islower():
        return market_key.replace("_", " ").title()
    return market_key


def format_value_bet_key(key: str, side: str) -> str:
    """Convierte 'batter_hits|Aaron Judge|0.5' + 'Over' en texto legible."""
    market_key, player, point = key.split("|")
    point_str = f" {point}" if point != "None" else ""
    return f"{market_label(market_key)} — {escape_md(player)}: {escape_md(side)}{point_str}"
