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

# Exactamente como aparece en Stake (español), para que se pueda buscar
NOMBRES_STAKE = {
    "pitcher_strikeouts": "Strikeouts",
    "batter_hits": "Golpes",
    "batter_home_runs": "Jonrones",
    "batter_rbis": "Carreras Remolcadas",
    "batter_runs_scored": "Carreras",
    "pitcher_outs": "Salidas del Campo",
    "batter_walks": "Caminatas",
    "batter_stolen_bases": "Bases Robadas",
    "batter_strikeouts": "Ponches (strikeouts) del bateador",
    "batter_hits_runs_rbis": "Golpes + Carreras + Carreras Remolcadas",
    "pitcher_hits_allowed": "Golpes Permitidos",
    "pitcher_earned_runs": "Carreras Conseguidas",
}


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
