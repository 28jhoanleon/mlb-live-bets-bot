"""Bug real: la web mostraba 'mañana' para partidos que en Stake estaban
EN VIVO. Causa: get_schedule() usaba date.today() (hora del sistema,
UTC en Railway) en vez de la hora de Argentina. De tardecita en
Argentina, el sistema ya está en el día siguiente en UTC, así que la
web le pedía a la MLB API la cartelera de MAÑANA -- el partido de HOY
que está en vivo ni aparece ahí, y en su lugar puede matchear con
cualquier otro partido de esos mismos equipos que caiga mañana (o
directamente no encontrar nada).

Lo llamativo: ya existía `hoy_local()` en app/utils/tiempo.py, con un
docstring que describe este bug exacto -- pero nunca se conectó a
get_schedule(), así que quedó ahí sin usarse."""
from datetime import date
from unittest.mock import patch

from app.mlb import schedule


def _schedule_vacio(*args, **kwargs):
    return {"dates": []}


class TestFechaDelCalendarioEsLaDeArgentina:
    def test_get_schedule_usa_hoy_local_no_la_del_sistema(self):
        """Simula el caso real: en Argentina todavía es 29 de julio a la
        noche, pero el sistema/UTC ya marca 30 de julio."""
        with patch.object(schedule, "hoy_local", return_value=date(2026, 7, 29)), \
             patch.object(schedule, "date") as fecha_mock, \
             patch("app.mlb.schedule.get", side_effect=_schedule_vacio) as get_mock:
            fecha_mock.today.return_value = date(2026, 7, 30)
            schedule.get_schedule()

        parametros_usados = get_mock.call_args.kwargs["params"]
        assert parametros_usados["date"] == "2026-07-29", (
            "get_schedule le pidió a la MLB API la fecha del sistema (UTC), "
            "no la de Argentina -- el bug que mostraba 'mañana' en partidos "
            "que ya estaban en vivo"
        )

    def test_cache_tambien_usa_hoy_local(self):
        schedule.limpiar_cache()
        with patch.object(schedule, "hoy_local", return_value=date(2026, 7, 29)), \
             patch.object(schedule, "date") as fecha_mock, \
             patch("app.mlb.schedule.get", side_effect=_schedule_vacio) as get_mock:
            fecha_mock.today.return_value = date(2026, 7, 30)
            schedule.get_schedule_cacheado()

        parametros_usados = get_mock.call_args.kwargs["params"]
        assert parametros_usados["date"] == "2026-07-29"
