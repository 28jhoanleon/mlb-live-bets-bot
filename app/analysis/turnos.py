"""Cuántos turnos al bate le quedan a un jugador en lo que resta del
partido.

Por qué importa: "necesita 1 hit" no dice nada por sí solo. Con 3 turnos
por delante es una apuesta viva; con medio turno en la novena, está casi
liquidada. Es la diferencia entre mirar el número y entender la
situación.

Cómo se estima: un equipo batea 9 jugadores por vuelta, así que a un
bateador le toca aproximadamente una vez cada 9 apariciones del equipo.
Sabiendo el inning y el orden al bate, se puede estimar cuántas vueltas
completas quedan y si al jugador le llega el turno en la última.

Es una ESTIMACIÓN, no una certeza: si el equipo arma una entrada larga
puede batear de más, y si va perdiendo por goleada la novena puede ser
corta. Se marca como aproximada a propósito -- prometer exactitud sobre
esto sería mentir.
"""
from __future__ import annotations

# Un partido de MLB dura 9 entradas salvo empate.
_ENTRADAS_REGLAMENTARIAS = 9
# Bateadores en el orden.
_BATEADORES_POR_VUELTA = 9
# Apariciones típicas de un equipo por entrada. Son 3 outs, pero suelen
# batear algunos más por hits y bases por bolas.
_APARICIONES_POR_ENTRADA = 4.3


def _orden_a_numero(batting_order) -> int | None:
    """La MLB API devuelve el orden como "301" (tercer bate, titular) o
    "1101" (suplente que entró por el primer bate). Solo interesan los
    centenares."""
    if batting_order is None:
        return None
    try:
        n = int(str(batting_order))
    except (TypeError, ValueError):
        return None
    puesto = n // 100
    return puesto if 1 <= puesto <= 9 else None


def turnos_restantes(
    batting_order,
    inning: int | None,
    inning_state: str | None,
    es_equipo_visitante: bool,
    outs: int | None = None,
) -> int | None:
    """Turnos que probablemente le queden al jugador.

    Devuelve None si falta información para estimarlo -- preferible a
    inventar un número que después no se cumple.
    """
    puesto = _orden_a_numero(batting_order)
    if puesto is None or not inning:
        return None

    # ¿Le queda al equipo por batear en esta entrada?
    estado = (inning_state or "").lower()
    arriba = estado.startswith("top") or "arriba" in estado
    batea_ahora = arriba if es_equipo_visitante else not arriba

    # Entradas completas que le quedan al equipo después de la actual.
    entradas_futuras = max(0, _ENTRADAS_REGLAMENTARIAS - inning)
    if not batea_ahora:
        # Si ahora batea el rival, a este equipo le queda su mitad de
        # esta misma entrada.
        entradas_futuras += 1

    apariciones = entradas_futuras * _APARICIONES_POR_ENTRADA

    # De la entrada en curso, lo que quede.
    if batea_ahora and outs is not None:
        apariciones += max(0.0, (3 - outs) * (_APARICIONES_POR_ENTRADA / 3))

    # A cada bateador le toca una vez cada 9 apariciones del equipo.
    turnos = int(apariciones / _BATEADORES_POR_VUELTA)

    # Ajuste por posición en el orden: los primeros del line-up baten
    # más veces que los últimos a lo largo del partido.
    if puesto <= 3 and apariciones % _BATEADORES_POR_VUELTA >= 3:
        turnos += 1

    return max(0, turnos)


def describir_turnos(turnos: int | None) -> str:
    """Texto corto para mostrar al lado de la leg."""
    if turnos is None:
        return ""
    if turnos == 0:
        return "sin turnos por delante"
    if turnos == 1:
        return "le queda ~1 turno"
    return f"le quedan ~{turnos} turnos"
