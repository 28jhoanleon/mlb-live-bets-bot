"""Análisis multimodal de capturas de apuestas usando OpenAI Vision.

Prioriza interpretación multimodal por sobre OCR clásico, tal como pide
el brief: el modelo lee la imagen completa (contexto visual + texto) en
vez de depender de extracción de texto pura, que falla con logos,
colores superpuestos, etc.
"""
from __future__ import annotations

import base64
import json
from typing import Any

import requests

from app.config import settings
from app.utils.logger import get_logger

log = get_logger(__name__)

_API_URL = "https://api.openai.com/v1/chat/completions"
_TIMEOUT = 30

_SYSTEM_PROMPT = """Sos un experto en lectura de capturas de pantalla de casas de apuestas deportivas (Bet365, Betano, Stake, DraftKings, FanDuel).

Tu tarea es identificar, de la imagen que te pasan, TODAS las selecciones de apuesta visibles. Para cada una extraé:
- partido (equipos)
- jugador (si es una prop individual)
- mercado
- línea
- cuota (odds decimal o americana, como esté en la imagen; null si la casa solo muestra la cuota total de la combinada)

REGLA CLAVE SOBRE "total_odds":
Es ÚNICAMENTE el número grande del encabezado de la tarjeta, el que está
al lado de textos como "Multi tramo", "Multi apuesta del mismo partido",
"Parlay" o "SGM" (ej: "11 Multi tramo   23,73" -> total_odds "23.73").

NUNCA uses la cuota de una selección individual como total_odds.
Si en la imagen NO se ve ese encabezado con su número, poné total_odds
en null. Es correcto y esperable: significa que la captura muestra solo
las selecciones, sin la cabecera.

SUB-GRUPOS DENTRO DE UNA COMBINADA:
Un "Multi tramo" grande suele estar dividido en bloques por partido, cada
uno titulado "Multi apuesta del mismo partido (N)" con SU PROPIA cuota
(ej: 1,68). Eso NO es un ticket aparte: es una parte del mismo.
En cada leg de ese bloque poné "group_odds" con esa cuota del bloque
(ej: "1.68"). Es distinta de "total_odds", que es la de toda la apuesta.

UNA COMBINADA PUEDE CRUZAR VARIOS PARTIDOS:
Un "Multi tramo" de 11 selecciones repartidas en 8 juegos distintos es
UNA sola apuesta, no ocho. No la separes por partido. Solo son tickets
distintos si ves recuadros separados, cada uno con SU propio encabezado
y su propia cuota total.

IMPORTANTE — NORMALIZACIÓN. La captura puede estar en cualquier idioma, pero vos SIEMPRE devolvés estos dos campos traducidos al inglés estándar:

"line": siempre "Over X" o "Under X".
  "Sobre 3.5" -> "Over 3.5"
  "Más de 6.5" -> "Over 6.5"
  "Menos de 2.5" -> "Under 2.5"
  "Bajo 1.5" -> "Under 1.5"

"market": usá EXACTAMENTE uno de estos nombres:
  Strikeouts, Batter Strikeouts, Hits, Runs, RBIs, Hits + Runs + RBIs,
  Home Runs, Walks, Stolen Bases, Outs, Hits Allowed, Earned Runs,
  Moneyline, Total
  Equivalencias frecuentes en español:
  "Ponches"/"Strikeouts" (de un pitcher) -> Strikeouts
  "Ponches" de un bateador -> Batter Strikeouts
  "Golpes" -> Hits
  "Golpes Permitidos" -> Hits Allowed
  "Caminatas"/"Boletos"/"Bases por bolas" -> Walks
  "Carreras" -> Runs
  "Carreras Remolcadas"/"Impulsadas" -> RBIs
  "Golpes + Carreras + Carreras Remolcadas" -> Hits + Runs + RBIs
  "Jonrones" -> Home Runs
  "Bases Robadas" -> Stolen Bases
  "Carreras Limpias" -> Earned Runs

Si un mercado no encaja en esa lista, devolvelo tal cual aparece en la imagen.

Si la imagen tiene una combinada (parlay) con varias legs, listá cada leg por separado.

Respondé ÚNICAMENTE con JSON válido, sin texto adicional, sin markdown.

IMPORTANTE — UNA CAPTURA PUEDE TENER VARIAS APUESTAS DISTINTAS.
Cada tarjeta/ticket separado (por ejemplo cada "Multi apuesta del mismo
partido" o "Same Game Multi", cada una con su propia cuota total) es una
APUESTA APARTE, aunque estén una al lado de la otra en la misma imagen.
No mezcles las selecciones de tickets distintos.

Formato:
{
  "is_live": true/false,
  "bets": [
    {
      "match": "Equipo A vs Equipo B",
      "total_odds": "2.95",
      "legs_declaradas": 11,
      "is_live": true,
      "legs": [
        {
          "match": "Equipo A vs Equipo B",
          "player": "Nombre del jugador o null",
          "market": "Strikeouts",
          "line": "Over 6.5",
          "odds": "1.90",
          "group_odds": "1.68"
        }
      ]
    }
  ]
}

- "bets": una entrada por cada ticket visible en la imagen.
- "total_odds": la cuota total de ese ticket (el número grande arriba a
  la derecha de la tarjeta). null si no se ve.
- "odds" dentro de cada leg: la cuota individual, o null si la casa solo
  muestra la cuota total del ticket.
- "match" dentro de cada leg: el partido al que pertenece ESA selección.
- "legs_declaradas": si la tarjeta dice cuántas selecciones tiene
  ("11 Multi tramo", "Multi apuesta del mismo partido (4)"), poné ese
  número. Sirve para detectar capturas incompletas. null si no figura.

CUIDADO — varios partidos NO significa varias apuestas.
Una combinada puede tener 11 o 15 selecciones de PARTIDOS DIFERENTES y
seguir siendo UN SOLO ticket. Lo que separa un ticket de otro es la
TARJETA y su CUOTA TOTAL, nunca la cantidad de partidos que toca.

  "11 Multi tramo ... 23,73"  -> UN ticket con 11 legs de varios partidos
  Dos tarjetas con dos cuotas -> DOS tickets

Ante la duda, agrupá: partir una combinada larga en pedazos rompe el
cálculo de probabilidad más de lo que lo rompe juntarlas.

"is_live" es true si la imagen muestra una etiqueta "Live", un inning en curso, o cualquier indicador de que el partido ya empezó. Si no hay ninguna señal de eso, poné false."""


class VisionAnalysisError(Exception):
    """Error al analizar la imagen con OpenAI Vision."""


def analyze_bet_screenshot(image_bytes: bytes) -> dict[str, Any]:
    """Envía la captura a OpenAI Vision y devuelve las selecciones
    detectadas ya parseadas como dict."""
    if not settings.openai_api_key:
        raise VisionAnalysisError(
            "Falta OPENAI_API_KEY. Cargala en tu .env / Railway vars."
        )

    b64_image = base64.b64encode(image_bytes).decode("utf-8")

    payload = {
        "model": settings.openai_vision_model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "Analizá esta captura de apuesta y extraé todas las selecciones.",
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{b64_image}"},
                    },
                ],
            },
        ],
        "max_tokens": 1000,
        "temperature": 0.1,
    }

    headers = {
        "Authorization": f"Bearer {settings.openai_api_key}",
        "Content-Type": "application/json",
    }

    try:
        resp = requests.post(_API_URL, headers=headers, json=payload, timeout=_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        log.error("Error llamando a OpenAI Vision: %s", exc)
        raise VisionAnalysisError(f"Fallo al analizar la imagen: {exc}") from exc

    try:
        content = data["choices"][0]["message"]["content"]
        # Por si el modelo igual envuelve en ```json a pesar del prompt
        cleaned = content.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        return json.loads(cleaned)
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        log.error("Respuesta inesperada de OpenAI Vision: %s", data)
        raise VisionAnalysisError(
            "No pude interpretar la respuesta del análisis de imagen."
        ) from exc
