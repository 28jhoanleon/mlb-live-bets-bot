"""LA causa raíz de toda la seguidilla de bugs de "muestra el partido
equivocado": la visión leía sólo los NOMBRES de los equipos de la
captura, nunca la fecha. Y Rangers @ Rays juegan varios días seguidos.

Sin fecha, elegir el partido correcto es imposible por definición, y
todos los intentos anteriores fueron heurísticas sobre un dato que
faltaba: "el que tenga datos" (agarraba el de ayer), "el más cercano a
ahora" (el ticket viejo se enganchaba al partido nuevo). Con la fecha
que ya está en la captura, deja de ser adivinanza.
"""
from datetime import date, datetime, timezone
from unittest.mock import patch

from app.mlb import live, schedule
from app.mlb.estados import mas_cercano_a, momento_de_la_captura

AYER = {
    "game_pk": 111, "status": "Final",
    "away_team": "Texas Rangers", "home_team": "Tampa Bay Rays",
    "game_time_utc": "2026-07-29T22:40:00Z",
}
HOY = {
    "game_pk": 222, "status": "Scheduled",
    "away_team": "Texas Rangers", "home_team": "Tampa Bay Rays",
    "game_time_utc": "2026-07-30T16:10:00Z",
}


def _por_dia(target_date=None):
    if target_date == date(2026, 7, 29):
        return [AYER]
    if target_date == date(2026, 7, 30):
        return [HOY]
    return []


class TestMomentoDeLaCaptura:
    def test_interpreta_hora_local_y_la_pasa_a_utc(self):
        momento = momento_de_la_captura("2026-07-30 13:10")
        assert momento is not None
        assert momento.tzinfo is not None

    def test_sin_fecha_devuelve_none_en_vez_de_inventar(self):
        assert momento_de_la_captura(None) is None
        assert momento_de_la_captura("") is None
        assert momento_de_la_captura("no es una fecha") is None


class TestElegirPorFechaDeLaCaptura:
    """El caso reportado: dos tickets del MISMO cruce, uno de ayer (ya
    perdido) y otro de hoy (activo). Cada uno tiene que engancharse a SU
    partido, no pisarse entre sí."""

    def test_el_ticket_de_ayer_se_queda_con_el_partido_de_ayer(self):
        with patch.object(live, "hoy_local", return_value=date(2026, 7, 30)), \
             patch.object(live, "get_schedule", side_effect=_por_dia), \
             patch.object(live, "get_live_game", return_value={"status": "Final"}):
            pk = live.find_live_game_by_teams(
                "texas rangers", "tampa bay rays", "2026-07-29 19:40"
            )
        assert pk == 111, "el ticket de ayer se enganchó al partido de hoy"

    def test_el_ticket_de_hoy_no_agarra_el_resultado_de_ayer(self):
        with patch.object(live, "hoy_local", return_value=date(2026, 7, 30)), \
             patch.object(live, "get_schedule", side_effect=_por_dia), \
             patch.object(live, "get_live_game", return_value={"status": "Final"}):
            pk = live.find_live_game_by_teams(
                "texas rangers", "tampa bay rays", "2026-07-30 13:10"
            )
        # El de hoy todavía no arrancó -> sin datos en vivo -> None.
        # Lo que NUNCA puede pasar es que devuelva el de ayer.
        assert pk != 111, (
            "el ticket de HOY agarró el resultado del partido de AYER: "
            "es exactamente el bug reportado"
        )

    def test_buscar_partido_tambien_respeta_la_fecha(self):
        schedule.limpiar_cache()
        with patch.object(schedule, "hoy_local", return_value=date(2026, 7, 30)), \
             patch.object(schedule, "get_schedule_cacheado", side_effect=_por_dia):
            de_ayer = schedule.buscar_partido(
                "texas rangers", "tampa bay rays", "2026-07-29 19:40"
            )
            de_hoy = schedule.buscar_partido(
                "texas rangers", "tampa bay rays", "2026-07-30 13:10"
            )

        assert de_ayer["game_pk"] == 111
        assert de_hoy["game_pk"] == 222

    def test_sin_fecha_sigue_funcionando_como_antes(self):
        """Las apuestas ya guardadas no tienen match_datetime: no deben
        romperse, sólo caer al respaldo por cercanía."""
        schedule.limpiar_cache()
        with patch.object(schedule, "hoy_local", return_value=date(2026, 7, 30)), \
             patch.object(schedule, "get_schedule_cacheado", side_effect=_por_dia):
            partido = schedule.buscar_partido("texas rangers", "tampa bay rays")
        assert partido is not None


class TestMasCercanoA:
    def test_elige_por_la_referencia_dada_no_por_ahora(self):
        referencia = datetime(2026, 7, 29, 22, 40, tzinfo=timezone.utc)
        assert mas_cercano_a([AYER, HOY], referencia)["game_pk"] == 111
