"""Identificación visual de equipos MLB.

Sobre los logos: Telegram NO permite incrustar imágenes dentro del texto
de un mensaje. Solo se puede mandar una imagen como mensaje aparte, lo
que en una combinada de 5 legs de 4 partidos distintos significaría
llenar el chat de fotos sueltas — peor que no tenerlas.

La alternativa que sí funciona en texto es la abreviatura oficial de
cada equipo (NYY, LAD, BOS). Es lo que usan los sitios de estadísticas
para identificar rápido, ocupa 3 caracteres y se lee de un vistazo.

Igual dejamos la URL del logo disponible por si más adelante se usa en
un mensaje con foto (por ejemplo, un pick individual destacado).
"""
from __future__ import annotations

# Abreviaturas oficiales por nombre completo del equipo
ABREVIATURAS = {
    "Arizona Diamondbacks": "ARI",
    "Atlanta Braves": "ATL",
    "Baltimore Orioles": "BAL",
    "Boston Red Sox": "BOS",
    "Chicago Cubs": "CHC",
    "Chicago White Sox": "CWS",
    "Cincinnati Reds": "CIN",
    "Cleveland Guardians": "CLE",
    "Colorado Rockies": "COL",
    "Detroit Tigers": "DET",
    "Houston Astros": "HOU",
    "Kansas City Royals": "KC",
    "Los Angeles Angels": "LAA",
    "Los Angeles Dodgers": "LAD",
    "Miami Marlins": "MIA",
    "Milwaukee Brewers": "MIL",
    "Minnesota Twins": "MIN",
    "New York Mets": "NYM",
    "New York Yankees": "NYY",
    "Athletics": "ATH",
    "Oakland Athletics": "ATH",
    "Philadelphia Phillies": "PHI",
    "Pittsburgh Pirates": "PIT",
    "San Diego Padres": "SD",
    "San Francisco Giants": "SF",
    "Seattle Mariners": "SEA",
    "St. Louis Cardinals": "STL",
    "Tampa Bay Rays": "TB",
    "Texas Rangers": "TEX",
    "Toronto Blue Jays": "TOR",
    "Washington Nationals": "WSH",
}

# IDs de la MLB Stats API, para construir la URL del logo
_TEAM_IDS = {
    "ARI": 109, "ATL": 144, "BAL": 110, "BOS": 111, "CHC": 112,
    "CWS": 145, "CIN": 113, "CLE": 114, "COL": 115, "DET": 116,
    "HOU": 117, "KC": 118, "LAA": 108, "LAD": 119, "MIA": 146,
    "MIL": 158, "MIN": 142, "NYM": 121, "NYY": 147, "ATH": 133,
    "PHI": 143, "PIT": 134, "SD": 135, "SF": 137, "SEA": 136,
    "STL": 138, "TB": 139, "TEX": 140, "TOR": 141, "WSH": 120,
}


def abreviatura(nombre_equipo: str | None) -> str:
    """'New York Yankees' -> 'NYY'. Si no lo conoce, arma una a partir
    de las iniciales para no quedarse sin nada."""
    if not nombre_equipo:
        return "?"
    nombre = nombre_equipo.strip()
    if nombre in ABREVIATURAS:
        return ABREVIATURAS[nombre]

    # Coincidencia parcial (la casa de apuestas puede escribirlo distinto)
    for completo, abrev in ABREVIATURAS.items():
        if completo.lower() in nombre.lower() or nombre.lower() in completo.lower():
            return abrev

    palabras = [p for p in nombre.split() if p]
    return "".join(p[0] for p in palabras[:3]).upper() or "?"


def abreviar_partido(match: str | None) -> str:
    """'New York Yankees @ Boston Red Sox' -> 'NYY @ BOS'."""
    if not match:
        return "?"
    for sep in (" @ ", " vs ", " - "):
        if sep in match:
            a, b = match.split(sep, 1)
            return f"{abreviatura(a)} @ {abreviatura(b)}"
    return abreviatura(match)


def url_logo(nombre_equipo: str | None) -> str | None:
    """URL del logo oficial (SVG). Útil solo si se manda como imagen."""
    abrev = abreviatura(nombre_equipo)
    team_id = _TEAM_IDS.get(abrev)
    if not team_id:
        return None
    return f"https://www.mlbstatic.com/team-logos/{team_id}.svg"


# Los apodos son ÚNICOS en MLB (no hay dos "Sox" iguales: están White Sox
# y Red Sox, pero se distinguen). Por eso se puede tirar la ciudad y sigue
# siendo inequívoco, ocupando mucho menos que el nombre completo.
_APODOS_ESPECIALES = {
    "Boston Red Sox": "Red Sox",
    "Chicago White Sox": "White Sox",
    "Toronto Blue Jays": "Blue Jays",
    "Tampa Bay Rays": "Rays",
    "Arizona Diamondbacks": "D-backs",
    "Athletics": "Athletics",
    "Oakland Athletics": "Athletics",
    "St. Louis Cardinals": "Cardinals",
    "Kansas City Royals": "Royals",
    "San Francisco Giants": "Giants",
    "San Diego Padres": "Padres",
    "Los Angeles Angels": "Angels",
    "Los Angeles Dodgers": "Dodgers",
    "New York Yankees": "Yankees",
    "New York Mets": "Mets",
}


def nombre_corto(nombre_equipo: str | None) -> str:
    """'New York Yankees' -> 'Yankees'. Legible sin conocer abreviaturas,
    pero sin ocupar toda la línea."""
    if not nombre_equipo:
        return "?"
    nombre = nombre_equipo.strip()

    if nombre in _APODOS_ESPECIALES:
        return _APODOS_ESPECIALES[nombre]

    for completo, apodo in _APODOS_ESPECIALES.items():
        if completo.lower() in nombre.lower():
            return apodo

    # Por defecto, la última palabra es el apodo (Braves, Cubs, Tigers...)
    palabras = nombre.split()
    return palabras[-1] if palabras else "?"


def partido_corto(match: str | None) -> str:
    """'New York Yankees @ Boston Red Sox' -> 'Yankees @ Red Sox'."""
    if not match:
        return "?"
    for sep in (" @ ", " vs ", " - "):
        if sep in match:
            a, b = match.split(sep, 1)
            return f"{nombre_corto(a)} @ {nombre_corto(b)}"
    return nombre_corto(match)


# IDs de la MLB Stats API. Son estables desde hace décadas y permiten
# armar la URL del logo oficial sin pedirle nada extra a la API.
_IDS_MLB = {
    "Los Angeles Angels": 108,
    "Arizona Diamondbacks": 109,
    "Baltimore Orioles": 110,
    "Boston Red Sox": 111,
    "Chicago Cubs": 112,
    "Cincinnati Reds": 113,
    "Cleveland Guardians": 114,
    "Colorado Rockies": 115,
    "Detroit Tigers": 116,
    "Houston Astros": 117,
    "Kansas City Royals": 118,
    "Los Angeles Dodgers": 119,
    "Washington Nationals": 120,
    "New York Mets": 121,
    "Oakland Athletics": 133,
    "Athletics": 133,
    "Pittsburgh Pirates": 134,
    "San Diego Padres": 135,
    "Seattle Mariners": 136,
    "San Francisco Giants": 137,
    "St. Louis Cardinals": 138,
    "Tampa Bay Rays": 139,
    "Texas Rangers": 140,
    "Toronto Blue Jays": 141,
    "Minnesota Twins": 142,
    "Philadelphia Phillies": 143,
    "Atlanta Braves": 144,
    "Chicago White Sox": 145,
    "Miami Marlins": 146,
    "New York Yankees": 147,
    "Milwaukee Brewers": 158,
}


def id_equipo(nombre: str | None) -> int | None:
    """ID del equipo en la MLB Stats API, buscando de forma tolerante
    porque los nombres pueden venir recortados de una captura."""
    if not nombre:
        return None
    limpio = nombre.strip()

    if limpio in _IDS_MLB:
        return _IDS_MLB[limpio]

    bajo = limpio.lower()
    for completo, tid in _IDS_MLB.items():
        if completo.lower() == bajo:
            return tid
    # Por apodo: "Yankees" -> New York Yankees
    for completo, tid in _IDS_MLB.items():
        if nombre_corto(completo).lower() == bajo:
            return tid
    for completo, tid in _IDS_MLB.items():
        if bajo in completo.lower() or completo.lower() in bajo:
            return tid
    return None


def logo_equipo(nombre: str | None) -> str | None:
    """URL del logo oficial. Devuelve None si no reconocemos al equipo,
    para que la interfaz simplemente no muestre imagen en vez de romperse."""
    tid = id_equipo(nombre)
    return f"https://www.mlbstatic.com/team-logos/{tid}.svg" if tid else None
