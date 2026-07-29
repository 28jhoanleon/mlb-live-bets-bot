"""Normalización y agrupación de apuestas (tickets).

Problema que resuelve: una captura puede contener VARIAS apuestas
distintas (en Stake, varias tarjetas "Multi apuesta del mismo partido",
cada una con su propia cuota). Antes se fusionaba todo en una sola
combinada gigante, lo cual es incorrecto: son tickets separados, cada
uno se gana o se pierde por su cuenta.

Este módulo:
  - Acepta tanto el formato nuevo (con "bets") como el viejo (lista
    plana de "legs"), para no romper apuestas ya guardadas en la base.
  - Si vienen legs sueltas de partidos distintos, las separa por partido:
    legs de partidos distintos no pueden ser el mismo ticket.
  - Fusiona capturas del mismo ticket sin duplicar legs.
"""
from __future__ import annotations

from typing import Any

from app.utils.logger import get_logger

log = get_logger(__name__)


def _leg_key(leg: dict) -> tuple:
    return (
        str(leg.get("player") or "").strip().lower(),
        str(leg.get("market") or "").strip().lower(),
        str(leg.get("line") or "").strip().lower(),
    )


def _match_key(texto: str | None) -> str:
    """Clave de partido tolerante al orden y al separador.

    'Pirates vs Diamondbacks' y 'Diamondbacks @ Pirates' son el mismo
    partido; si no las unificáramos, el mismo ticket se partiría en dos.
    """
    if not texto:
        return ""
    limpio = texto.lower()
    for sep in (" vs ", " @ ", " - ", " v "):
        limpio = limpio.replace(sep, "|")
    partes = sorted(p.strip() for p in limpio.split("|") if p.strip())
    return "|".join(partes)


def _dividir_por_partido(ticket: dict[str, Any]) -> list[dict[str, Any]]:
    """Red de seguridad: si un ticket trae legs de partidos distintos,
    lo parte en uno por partido.

    Por qué hace falta: la IA a veces junta en un solo ticket varias
    tarjetas que están una al lado de la otra en la captura. Confiar solo
    en que el modelo acierte daría conteos y probabilidades sin sentido
    (11 legs de 4 apuestas distintas tratadas como una combinada única).

    Solo aplica cuando las legs declaran su partido y son más de uno.
    """
    legs = ticket.get("legs") or []
    partidos = {_match_key(leg.get("match")) for leg in legs if leg.get("match")}

    # Un solo partido (o legs sin partido declarado): se deja como está
    if len(partidos) <= 1:
        return [ticket]

    por_partido: dict[str, list[dict]] = {}
    for leg in legs:
        por_partido.setdefault(_match_key(leg.get("match")), []).append(leg)

    return [
        {
            "match": grupo[0].get("match", ""),
            # La cuota total del ticket original ya no aplica a las partes
            "total_odds": None,
            "is_live": ticket.get("is_live", False),
            "legs": grupo,
        }
        for grupo in por_partido.values()
    ]


def normalize(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    """Devuelve siempre una lista de tickets, venga en el formato que venga."""
    if not analysis:
        return []

    # Formato nuevo: la IA ya separó los tickets
    if analysis.get("bets"):
        tickets = []
        for bet in analysis["bets"]:
            legs = bet.get("legs") or []
            if not legs:
                continue
            ticket = {
                "match": bet.get("match") or (legs[0].get("match") if legs else ""),
                "total_odds": bet.get("total_odds"),
                "is_live": bool(bet.get("is_live", analysis.get("is_live"))),
                "legs": legs,
            }
            tickets.extend(_dividir_por_partido(ticket))
        return tickets

    # Formato viejo: lista plana de legs. Las agrupamos por partido,
    # porque legs de partidos distintos nunca son el mismo ticket.
    legs = analysis.get("legs") or []
    if not legs:
        return []

    por_partido: dict[str, list[dict]] = {}
    for leg in legs:
        por_partido.setdefault(_match_key(leg.get("match")), []).append(leg)

    return [
        {
            "match": grupo[0].get("match", ""),
            "total_odds": None,
            "is_live": bool(analysis.get("is_live")),
            "legs": grupo,
        }
        for grupo in por_partido.values()
    ]


def _fusionar_ticket(a: dict, b: dict) -> dict:
    """Une dos vistas del mismo ticket (por ejemplo dos capturas que se
    solapan al scrollear), sin repetir legs."""
    legs: list[dict] = []
    vistas: set[tuple] = set()
    for leg in list(a.get("legs", [])) + list(b.get("legs", [])):
        clave = _leg_key(leg)
        if clave in vistas:
            continue
        vistas.add(clave)
        legs.append(leg)

    return {
        "match": a.get("match") or b.get("match"),
        "total_odds": a.get("total_odds") or b.get("total_odds"),
        "is_live": bool(a.get("is_live") or b.get("is_live")),
        "legs": legs,
    }


def _ticket_key(ticket: dict) -> tuple:
    """Dos tickets son el mismo si son del mismo partido y tienen la
    misma cuota total. Sin la cuota, dos SGM distintos del mismo partido
    se fusionarían por error."""
    return (_match_key(ticket.get("match")), str(ticket.get("total_odds") or ""))


def merge_tickets(listas: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Fusiona tickets de varias capturas. Mismo ticket -> se unen sus
    legs; tickets distintos -> quedan separados."""
    resultado: dict[tuple, dict] = {}
    orden: list[tuple] = []

    for tickets in listas:
        for ticket in tickets:
            if not ticket.get("legs"):
                continue
            clave = _ticket_key(ticket)
            if clave in resultado:
                resultado[clave] = _fusionar_ticket(resultado[clave], ticket)
            else:
                resultado[clave] = ticket
                orden.append(clave)

    return [resultado[k] for k in orden]


def to_storage(tickets: list[dict[str, Any]]) -> dict[str, Any]:
    """Empaqueta los tickets para guardarlos en la base."""
    return {
        "bets": tickets,
        "is_live": any(t.get("is_live") for t in tickets),
    }
