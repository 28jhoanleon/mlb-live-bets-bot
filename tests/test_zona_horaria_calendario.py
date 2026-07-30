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
from datetime import date, datetime
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
    """Bug real #1: Dodgers @ Mariners arrancó 23:10 hora Argentina y
    siguió en curso pasada la medianoche. Para ese momento hoy_local()
    ya apuntaba al día siguiente, así que buscar_partido() dejó de ver
    ese partido en 'la cartelera de hoy'.

    Bug real #2 (la vuelta siguiente, y el más importante): al arreglar
    el #1 prefiriendo ciegamente "cualquiera con datos", una serie de
    varios días entre los mismos dos equipos rompió al revés: un ticket
    sobre el partido de MAÑANA (todavía sin arrancar) terminó mostrando
    el resultado de un partido YA JUGADO entre esos mismos equipos, de
    otro día de la misma serie. La solución final: elegir el candidato
    de fecha/hora más cercana a AHORA, sea pasado o futuro -no
    "cualquiera con datos" ni "siempre el de más adelante"."""

    def _schedule(self, game_time_utc: str, extra: dict) -> list[dict]:
        base = {
            "away_team": "Los Angeles Dodgers", "home_team": "Seattle Mariners",
            "venue": "T-Mobile Park", "game_time_utc": game_time_utc,
        }
        return [{**base, **extra}]

    def _ahora(self, iso: str):
        return patch(
            "app.mlb.estados.datetime",
            **{
                "now.return_value": datetime.fromisoformat(iso),
                "fromisoformat.side_effect": datetime.fromisoformat,
            },
        )

    def test_prioriza_el_partido_de_ayer_si_sigue_vivo_o_termino(self):
        """Son las 00:30 en Argentina (02:30 UTC), recién pasada la
        medianoche: el partido de ayer, que arrancó 23:10 ART (02:10 UTC,
        ya del día siguiente) y todavía sigue en curso, tiene que
        ganarle al próximo de la serie, programado para bastante más
        tarde."""
        ayer_pk, hoy_pk = 111, 222
        with patch.object(schedule, "hoy_local", return_value=date(2026, 7, 30)), \
             patch.object(schedule, "get_schedule_cacheado") as sched_mock, \
             self._ahora("2026-07-30T02:30:00+00:00"):
            def _fake(target_date=None):
                if target_date == date(2026, 7, 29):
                    # Se consulta como "29" (la fecha de calendario en
                    # que arrancó en Argentina) pero en UTC ya cae 30.
                    return self._schedule("2026-07-30T02:10:00Z", {"game_pk": ayer_pk, "status": "Final"})
                return self._schedule("2026-07-30T23:10:00Z", {"game_pk": hoy_pk, "status": "Scheduled"})

            sched_mock.side_effect = _fake
            partido = schedule.buscar_partido("los angeles dodgers", "seattle mariners")

        assert partido is not None
        assert partido["game_pk"] == ayer_pk, (
            "devolvió el próximo partido de la serie (todavía sin arrancar) "
            "en vez del de ayer, que siguió en curso pasada la medianoche"
        )

    def test_si_ayer_no_tiene_datos_cae_a_hoy(self):
        """No romper el caso normal: si ayer no hay nada relevante, usar
        la cartelera de hoy."""
        hoy_pk = 222
        with patch.object(schedule, "hoy_local", return_value=date(2026, 7, 30)), \
             patch.object(schedule, "get_schedule_cacheado") as sched_mock, \
             self._ahora("2026-07-30T01:50:00+00:00"):
            def _fake(target_date=None):
                if target_date == date(2026, 7, 29):
                    return []  # nada ayer
                return self._schedule("2026-07-30T02:10:00Z", {"game_pk": hoy_pk, "status": "Scheduled"})

            sched_mock.side_effect = _fake
            partido = schedule.buscar_partido("los angeles dodgers", "seattle mariners")

        assert partido is not None
        assert partido["game_pk"] == hoy_pk

    def test_serie_de_varios_dias_elige_el_partido_correcto_no_cualquiera_con_datos(self):
        """El bug real reportado: Rangers @ Rays (y otros) jugaban una
        serie de varios días. El ticket era sobre el partido de MAÑANA
        (todavía sin arrancar), pero al preferir ciegamente cualquier
        partido 'con datos', devolvía el de HACE DOS DÍAS -ya terminado
        Final- entre esos mismos dos equipos. El de mañana tiene que
        ganar porque está más cerca de AHORA."""
        viejo_pk, correcto_pk = 111, 333
        with patch.object(schedule, "hoy_local", return_value=date(2026, 7, 29)), \
             patch.object(schedule, "get_schedule_cacheado") as sched_mock, \
             self._ahora("2026-07-29T22:00:00+00:00"):  # noche del 29, el de mañana es a la tarde
            def _fake(target_date=None):
                if target_date == date(2026, 7, 27):  # hace 2 dias: ya jugado
                    return self._schedule("2026-07-27", {"game_pk": viejo_pk, "status": "Final"})
                if target_date == date(2026, 7, 30):  # mañana: el que corresponde
                    return [{
                        "away_team": "Texas Rangers", "home_team": "Tampa Bay Rays",
                        "venue": "Tropicana Field", "game_time_utc": "2026-07-30T17:10:00Z",
                        "game_pk": correcto_pk, "status": "Scheduled",
                    }]
                return []

            sched_mock.side_effect = _fake
            partido = schedule.buscar_partido("texas rangers", "tampa bay rays")

        assert partido is not None
        assert partido["game_pk"] == correcto_pk, (
            f"devolvió un partido YA JUGADO de hace 2 días ({partido}) en vez "
            f"del de mañana, que es el que corresponde a este ticket"
        )
