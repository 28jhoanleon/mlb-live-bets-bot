"""Barra de progreso estilo Stake.

Replica el slider de Stake en texto: una línea continua, el valor actual
del jugador a la izquierda, y a la derecha el número que hace falta
alcanzar. Cuando la leg se cumple, el check reemplaza a ese número —
igual que en Stake, donde el objetivo desaparece y queda el tilde verde.

    3 ━━━━━━━━━─── 4     (le faltan ponches)
    7 ━━━━━━━━━━━━ ✅    (cumplida)

Nota sobre el contraste: la parte no cumplida usa una línea fina. Es
sutil a propósito, igual que en Stake — la información precisa está en
los números, la barra da la sensación de avance.
"""
from __future__ import annotations

import math

_FILLED = "━"
_EMPTY = "─"
_LARGO = 12


def target_needed(threshold: float, side: str = "Over") -> float:
    """Número concreto que hace falta alcanzar.

    Las casas no muestran la línea (3.5) sino el entero al que hay que
    llegar (4), que es lo que realmente le importa al apostador.
    """
    if side == "Over":
        return float(math.floor(threshold) + 1)
    return float(threshold)


def build_progress_bar(
    current: float,
    threshold: float,
    side: str = "Over",
    length: int = _LARGO,
    already_hit: bool | None = None,
    show_check: bool = True,
    state: str | None = None,
) -> str:
    """Dibuja la barra.

    `state` se acepta por compatibilidad con el tracking en vivo, pero
    en este estilo el color no se usa: Telegram no soporta texto de
    color y la señal la dan el check y el emoji del título de la leg.
    """
    objetivo = target_needed(threshold, side)

    if already_hit is None:
        already_hit = current > threshold if side == "Over" else current < threshold
    if state == "done":
        already_hit = True

    ratio = 1.0 if already_hit else (min(current / objetivo, 1.0) if objetivo > 0 else 1.0)
    filled = max(0, min(length, round(ratio * length)))
    bar = _FILLED * filled + _EMPTY * (length - filled)

    # Como en Stake: al cumplirse, el objetivo deja de importar y queda el tilde
    derecha = "✅" if (already_hit and show_check) else _fmt(objetivo)
    return f"{_fmt(current)} {bar} {derecha}"


def _fmt(value: float) -> str:
    """Muestra 3 en vez de 3.0, pero conserva 3.5."""
    return str(int(value)) if float(value).is_integer() else str(value)


def build_form_bar(hits: int, total: int, length: int = _LARGO) -> str:
    """Barra de forma reciente: en cuántos de sus últimos partidos el
    jugador superó esa línea.

    Ojo, mide algo DISTINTO a build_progress_bar: no es el avance hacia
    el objetivo de hoy, sino la regularidad histórica. Por eso el texto
    que la acompaña tiene que aclararlo ("8 de sus últimos 10").

    Existe para que todas las legs tengan una referencia visual: antes
    las legs en vivo tenían barra y las históricas no, y la lista se veía
    cortada a la mitad.
    """
    if total <= 0:
        return ""
    ratio = max(0.0, min(hits / total, 1.0))
    filled = max(0, min(length, round(ratio * length)))
    # "8 de 10" y no "8/10": al lado de una línea como "Over 0.5",
    # el formato con barra se leía como si el objetivo fuera 10.
    return f"{_FILLED * filled}{_EMPTY * (length - filled)}  {hits} de {total}"
