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
    """Red de seguridad para cuando la IA junta varias tarjetas en una.

    OJO con el criterio: "legs de partidos distintos" NO significa
    tickets distintos. Una combinada normal de varios partidos (11 o 15
    tramos) es UN solo ticket con legs de muchos juegos. Partirla estaría
    igual de mal que fusionar cuatro tickets en uno.

    Lo que sí identifica a un ticket real es su CUOTA TOTAL: es el número
    que la casa muestra en la tarjeta. Si el ticket la tiene, confiamos en
    que la IA leyó bien un recuadro y no lo tocamos.

    Solo dividimos cuando no hay cuota total Y las legs abarcan varios
    partidos: ahí es probable que la IA haya mezclado tarjetas vecinas.
    """
    legs = ticket.get("legs") or []

    # La cuota total es la huella de un ticket real: no lo partimos.
    if ticket.get("total_odds"):
        return [ticket]

    # Tampoco lo partimos si las legs traen "group_odds": esa es la cuota
    # de cada bloque DENTRO de un mismo cupón. Que existan varios bloques
    # es justamente la forma de un cupón combinado de varios partidos, no
    # la señal de que sean apuestas distintas.
    #
    # Bug real: un cupón con cuatro bloques (5.00, 2.36, 1.92, 3.55) y sin
    # total visible se partía en cuatro apuestas separadas, aunque el
    # usuario lo estaba jugando como una sola combinada.
    if any(leg.get("group_odds") for leg in legs):
        return [ticket]

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
                "label": bet.get("label") or analysis.get("label"),
                "legs_declaradas": bet.get("legs_declaradas"),
                "is_live": bool(bet.get("is_live", analysis.get("is_live"))),
                # La marca de borrador tiene que sobrevivir a normalize:
                # se reconstruye el ticket con una lista fija de campos y
                # cualquier otro se pierde. Sin esto, una apuesta guardada
                # con "probar" se veía en la web como si fuera real, sin
                # el cartel ni los botones de confirmar/descartar.
                "borrador": bool(bet.get("borrador")),
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
        "label": a.get("label") or b.get("label"),
        "total_odds": a.get("total_odds") or b.get("total_odds"),
        "is_live": bool(a.get("is_live") or b.get("is_live")),
        "legs": legs,
    }


def _ticket_key(ticket: dict) -> tuple:
    # Si el usuario puso una etiqueta en el pie de foto, manda ella: es la
    # única señal confiable cuando la captura no muestra el encabezado de
    # la tarjeta (pasa siempre al desplegar una combinada larga).
    etiqueta = str(ticket.get("label") or "").strip().lower()
    if etiqueta:
        return ("label", etiqueta)

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


def unificar_cupon(tickets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Varios bloques de UNA captura son UNA sola apuesta.

    El cupón de Stake muestra la combinada partida en bloques ("Multi
    apuesta del mismo partido"), uno por partido, cada uno con su cuota
    parcial. La IA los lee como apuestas separadas y terminabas viendo
    cinco tarjetas de "2 TRAMOS" cuando habías jugado una sola.

    La señal de que son apuestas DISTINTAS es que cada una traiga su
    propia cuota total (o su propio importe/pago). Si ninguna la tiene,
    son partes del mismo cupón y se unen.
    """
    if len(tickets) <= 1:
        return tickets

    con_total = [t for t in tickets if t.get("total_odds")]
    if len(con_total) > 1:
        # Cada una tiene su cuota total: son apuestas separadas de verdad.
        return tickets

    unido: dict[str, Any] = {
        "legs": [leg for t in tickets for leg in t.get("legs", [])],
    }
    # Si UNA traía la cuota total, es la del cupón entero.
    if con_total:
        unido["total_odds"] = con_total[0]["total_odds"]

    for clave in ("label", "legs_declaradas", "is_live", "borrador"):
        for t in tickets:
            if t.get(clave):
                unido[clave] = t[clave]
                break

    return [unido]
