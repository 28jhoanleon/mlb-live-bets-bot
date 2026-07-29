"""Manejo de horarios.

La MLB Stats API devuelve todo en UTC. Mostrar esa hora tal cual obliga a
hacer la cuenta mental cada vez, así que la convertimos a la zona del
usuario (TZ_NAME en el .env, por defecto Buenos Aires).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo

from app.config import settings
from app.utils.logger import get_logger

log = get_logger(__name__)


def zona_local() -> tzinfo:
    """Zona horaria del usuario, con respaldo seguro.

    Ojo con el respaldo: en Termux (y en imágenes de Linux muy chicas)
    Python no trae la base de datos de zonas horarias, así que hasta
    `ZoneInfo("UTC")` explota. Por eso caemos a `timezone.utc`, que es
    de la biblioteca estándar y no depende de archivos externos.

    Para que la conversión a hora argentina funcione de verdad hace
    falta el paquete `tzdata` (está en requirements.txt).
    """
    try:
        return ZoneInfo(settings.timezone)
    except Exception:
        log.warning(
            "Zona horaria '%s' no disponible (¿falta el paquete tzdata?), uso UTC",
            settings.timezone,
        )
        return timezone.utc


def a_local(iso_utc: str | None) -> datetime | None:
    """Convierte un timestamp ISO de la API a datetime en zona local."""
    if not iso_utc:
        return None
    try:
        dt = datetime.fromisoformat(iso_utc.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(zona_local())


def formato_hora(iso_utc: str | None) -> str:
    """'19:40' en hora argentina, o 'Hora TBD' si no hay dato."""
    dt = a_local(iso_utc)
    return dt.strftime("%H:%M") if dt else "Hora TBD"


def formato_hora_fecha(iso_utc: str | None) -> str:
    """Agrega el día cuando el partido NO es hoy en hora local.

    Un partido de las 22:00 UTC puede caer hoy o mañana según la zona;
    mostrar solo la hora en ese caso confunde.
    """
    dt = a_local(iso_utc)
    if not dt:
        return "Hora TBD"
    hoy = datetime.now(zona_local()).date()
    if dt.date() == hoy:
        return dt.strftime("%H:%M")
    if dt.date() == hoy + timedelta(days=1):
        return dt.strftime("mañana %H:%M")
    return dt.strftime("%d/%m %H:%M")


def hoy_local() -> date:
    """La fecha de hoy según la zona del usuario.

    Importa: a las 22:00 en Argentina ya es el día siguiente en UTC, así
    que pedir 'los partidos de hoy' con la fecha UTC traería la cartelera
    equivocada.
    """
    return datetime.now(zona_local()).date()


# Un partido de MLB dura ~3 horas; con 4 damos margen a extra innings.
_DURACION_MAX_PARTIDO = timedelta(hours=4)


def evento_vigente(commence_time: str | None) -> bool:
    """True si el partido todavía no terminó (o ni siquiera empezó).

    Sirve para no sugerir picks de partidos ya jugados: The Odds API a
    veces sigue devolviendo eventos viejos en la lista.
    """
    if not commence_time:
        return False
    inicio = a_local(commence_time)
    if not inicio:
        return False
    ahora = datetime.now(zona_local())
    return inicio + _DURACION_MAX_PARTIDO > ahora
