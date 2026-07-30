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


class TestBuscarPartidoVariosDiasAtras:
    """Mismo bug que en find_live_game_by_teams, pero en buscar_partido
    (la usa service.py para saber si vale la pena pedir datos en vivo)."""

    def test_encuentra_partido_de_dos_dias_atras(self):
        def _fake_get(path, params=None, **kwargs):
            if params.get("date") == "2026-07-28":
                return {
                    "dates": [{"games": [{
                        "gamePk": 555,
                        "status": {"detailedState": "Final"},
                        "teams": {
                            "away": {"team": {"name": "Philadelphia Phillies"}},
                            "home": {"team": {"name": "Miami Marlins"}},
                        },
                        "venue": {"name": "loanDepot park"},
                        "gameDate": "2026-07-28T23:10:00Z",
                    }]}]
                }
            return {"dates": []}

        schedule.limpiar_cache()
        with patch.object(schedule, "hoy_local", return_value=date(2026, 7, 30)), \
             patch("app.mlb.schedule.get", side_effect=_fake_get):
            partido = schedule.buscar_partido("phillies", "marlins")

        assert partido is not None
        assert partido["status"] == "Final"


class TestBuscarPartidoNocturno:
    """Bug real: Dodgers @ Mariners arrancó 23:10 hora Argentina y siguió
    en curso pasada la medianoche. Para ese momento hoy_local() ya
    apuntaba al día siguiente, así que buscar_partido() dejó de ver ese
    partido en 'la cartelera de hoy' -y como esos mismos equipos también
    tenían otro partido programado para el día siguiente (serie de
    varios juegos), terminó devolviendo ESE, todavía sin arrancar. La web
    mostraba el reloj de 'programado' para un partido que en la vida real
    ya había terminado 4-2."""

    def _schedule(self, dia: str, extra: dict) -> list[dict]:
        base = {
            "away_team": "Los Angeles Dodgers", "home_team": "Seattle Mariners",
            "venue": "T-Mobile Park", "game_time_utc": f"{dia}T02:10:00Z",
        }
        return [{**base, **extra}]

    def test_prioriza_el_partido_de_ayer_si_sigue_vivo_o_termino(self):
        ayer_pk = 111
        hoy_pk = 222
        with patch.object(schedule, "hoy_local", return_value=date(2026, 7, 30)), \
             patch.object(schedule, "get_schedule_cacheado") as sched_mock:
            def _fake(target_date=None):
                if target_date == date(2026, 7, 29):
                    return self._schedule("2026-07-29", {"game_pk": ayer_pk, "status": "Final"})
                return self._schedule("2026-07-30", {"game_pk": hoy_pk, "status": "Scheduled"})

            sched_mock.side_effect = _fake
            partido = schedule.buscar_partido("los angeles dodgers", "seattle mariners")

        assert partido is not None
        assert partido["game_pk"] == ayer_pk, (
            "devolvió el partido de HOY (todavía sin arrancar) en vez del "
            "de ayer, que siguió en curso pasada la medianoche"
        )

    def test_si_ayer_no_tiene_datos_cae_a_hoy(self):
        """No romper el caso normal: si ayer no hay nada relevante, usar
        la cartelera de hoy."""
        hoy_pk = 222
        with patch.object(schedule, "hoy_local", return_value=date(2026, 7, 30)), \
             patch.object(schedule, "get_schedule_cacheado") as sched_mock:
            def _fake(target_date=None):
                if target_date == date(2026, 7, 29):
                    return []  # nada ayer
                return self._schedule("2026-07-30", {"game_pk": hoy_pk, "status": "Scheduled"})

            sched_mock.side_effect = _fake
            partido = schedule.buscar_partido("los angeles dodgers", "seattle mariners")

        assert partido is not None
        assert partido["game_pk"] == hoy_pk
