"""Tests de regresión para los bugs encontrados probando en vivo con una
combinada real de Stake en español (Rangers vs Mariners).

Los tres bugs:
1. Mercados en español mal clasificados. 'Golpes + Carreras + Carreras
   Remolcadas' matcheaba con 'carrera' y contaba SOLO carreras -> daba
   una probabilidad equivocada en una leg que ya estaba ganada.
2. Falso "ya salió del partido": se comparaba al pitcher contra el que
   lanza en ese momento en el partido. Cuando el equipo del jugador
   estaba bateando, ese era el pitcher rival -> falso positivo.
3. Barra de progreso poco clara; ahora muestra valor actual y objetivo
   como el slider de Stake.
"""
import pytest

from app.analysis.live_tracking import _check_active_status
from app.analysis.probability import (
    ProbabilityError,
    _classify_batter_market,
    _classify_pitcher_market,
)
from app.utils.progress_bar import _EMPTY, _FILLED, build_progress_bar, target_needed


class TestMercadosEnEspanol:
    def test_combinado_hrrbi_en_espanol_no_cuenta_solo_carreras(self):
        """El bug: devolvía ['runs'] en vez de los tres campos."""
        assert _classify_batter_market("Golpes + Carreras + Carreras Remolcadas") == [
            "hits",
            "runs",
            "rbi",
        ]

    def test_combinado_hrrbi_en_ingles(self):
        assert _classify_batter_market("Hits + Runs + RBIs") == ["hits", "runs", "rbi"]

    @pytest.mark.parametrize(
        "texto,esperado",
        [
            ("Golpes", ["hits"]),
            ("Carreras", ["runs"]),
            ("Carreras Remolcadas", ["rbi"]),
            ("Jonrones", ["home_runs"]),
            ("Bases Robadas", ["stolen_bases"]),
            ("Caminatas", ["walks"]),
            ("Batter Strikeouts", ["strikeouts"]),
        ],
    )
    def test_mercados_de_bateo(self, texto, esperado):
        assert _classify_batter_market(texto) == esperado

    @pytest.mark.parametrize(
        "texto,esperado",
        [
            ("Golpes Permitidos", ["hits_allowed"]),
            ("Hits Allowed", ["hits_allowed"]),
            ("Caminatas", ["walks"]),
            ("Ponches", ["strikeouts"]),
            ("Outs", ["outs"]),
            ("Carreras Limpias", ["earned_runs"]),
        ],
    )
    def test_mercados_de_pitcheo(self, texto, esperado):
        assert _classify_pitcher_market(texto) == esperado

    def test_mercado_desconocido_avisa_en_vez_de_adivinar(self):
        with pytest.raises(ProbabilityError):
            _classify_batter_market("Mercado Inventado XYZ")


class TestEstadoDelPitcher:
    def _stats(self, **kwargs):
        base = {
            "is_team_last_pitcher": True,
            "is_current_pitcher": False,
            "pitching": {"outs": 18},
        }
        base.update(kwargs)
        return base

    def test_pitcher_de_equipo_que_batea_no_se_marca_como_salido(self):
        """El bug: su equipo estaba bateando, así que el 'pitcher actual'
        era el del rival, y lo dábamos por sustituido."""
        estado = _check_active_status(
            "George Kirby",
            self._stats(is_team_last_pitcher=True),
            is_pitcher=True,
            current_pitcher="Michael Rucker",  # pitcher del OTRO equipo
        )
        assert "🟢" in estado
        assert "salió" not in estado

    def test_pitcher_realmente_sustituido_se_detecta(self):
        estado = _check_active_status(
            "George Kirby",
            self._stats(is_team_last_pitcher=False),
            is_pitcher=True,
            current_pitcher="Michael Rucker",
        )
        assert "🔴" in estado
        assert "salió" in estado

    def test_pitcher_que_no_lanzo_todavia(self):
        estado = _check_active_status(
            "Relevista X",
            self._stats(is_team_last_pitcher=False, pitching={"outs": 0}),
            is_pitcher=True,
            current_pitcher="Otro",
        )
        assert "❓" in estado

    def test_titular_no_se_marca_como_banco(self):
        """Bug: `isOnBench` da true para cualquier jugador que no esté
        bateando en ese instante, incluidos los titulares mientras su
        equipo defiende. Pintaba de rojo legs con 80% de probabilidad."""
        estado = _check_active_status(
            "Bateador Y",
            {"is_on_bench": True, "batting_order": "500", "pitching": {}},
            is_pitcher=False,
            current_pitcher=None,
        )
        assert "🟢" in estado
        assert "banco" not in estado

    def test_suplente_sin_orden_de_bateo_no_se_da_por_perdido(self):
        """Todavía puede entrar al partido: no es rojo, es incertidumbre."""
        estado = _check_active_status(
            "Suplente Z",
            {"is_on_bench": True, "batting_order": None, "pitching": {}},
            is_pitcher=False,
            current_pitcher=None,
        )
        assert "🔴" not in estado
        assert "❓" in estado


class TestBarraEstiloStake:
    """Estilo Stake: línea continua, valor actual a la izquierda y
    objetivo a la derecha. Al cumplirse, el check reemplaza al objetivo
    (en Stake el número desaparece y queda el tilde verde)."""

    def test_muestra_actual_y_objetivo(self):
        barra = build_progress_bar(3, 3.5)
        assert barra.startswith("3 ")
        assert barra.endswith(" 4")

    def test_al_cumplirse_el_check_reemplaza_al_objetivo(self):
        barra = build_progress_bar(7, 4.5)
        assert barra.endswith("✅")
        assert " 5" not in barra

    def test_objetivo_es_el_entero_a_alcanzar(self):
        assert target_needed(3.5, "Over") == 4
        assert target_needed(1.5, "Over") == 2

    def test_barra_llena_al_cumplirse(self):
        assert _EMPTY not in build_progress_bar(7, 4.5)

    def test_barra_vacia_sin_progreso(self):
        assert _FILLED not in build_progress_bar(0, 6.5)

    def test_no_se_pasa_del_largo(self):
        barra = build_progress_bar(50, 1.5, length=10)
        assert barra.count(_FILLED) == 10

    def test_largo_constante_entre_legs(self):
        """Todas las barras miden lo mismo para que se alineen."""
        a = build_progress_bar(3, 3.5, length=12)
        b = build_progress_bar(6, 14.5, length=12)
        assert a.count(_FILLED) + a.count(_EMPTY) == 12
        assert b.count(_FILLED) + b.count(_EMPTY) == 12


class TestLineasEnEspanol:
    """Bug: la IA devolvió 'Sobre 3.5' (español) y el parser solo
    entendía Over/Under/Más/Menos -> fallaban las 4 legs."""

    @pytest.mark.parametrize(
        "texto,esperado",
        [
            ("Sobre 3.5", ("Over", 3.5)),
            ("Sobre 1.5", ("Over", 1.5)),
            ("Over 6.5", ("Over", 6.5)),
            ("Under 14.5", ("Under", 14.5)),
            ("Más de 2.5", ("Over", 2.5)),
            ("Menos de 3.5", ("Under", 3.5)),
            ("Bajo 5.5", ("Under", 5.5)),
            ("Debajo de 2.5", ("Under", 2.5)),
            ("Arriba de 1.5", ("Over", 1.5)),
            ("Encima de 2.5", ("Over", 2.5)),
            ("O 3.5", ("Over", 3.5)),
            ("U 4.5", ("Under", 4.5)),
            ("Sobre 3,5", ("Over", 3.5)),
        ],
    )
    def test_parsea_lineas(self, texto, esperado):
        from app.analysis.probability import _parse_line

        assert _parse_line(texto) == esperado

    def test_sin_direccion_falla_en_vez_de_adivinar(self):
        """Confundir Under con Over daría la probabilidad al revés, así
        que preferimos avisar antes que inventar."""
        from app.analysis.probability import _parse_line

        with pytest.raises(ProbabilityError):
            _parse_line("3.5")


class TestBarraDeFormaReciente:
    """Todas las legs deben tener referencia visual. Antes solo la tenían
    las que se podían seguir en vivo, así que la lista se veía cortada:
    las primeras legs con barra y el resto sin nada."""

    def test_dibuja_la_proporcion(self):
        from app.utils.progress_bar import build_form_bar

        barra = build_form_bar(8, 10, length=10)
        assert barra.endswith("8 de 10")
        assert barra.count(_FILLED) == 8
        assert barra.count(_EMPTY) == 2

    def test_sin_partidos_no_rompe(self):
        from app.utils.progress_bar import build_form_bar

        assert build_form_bar(0, 0) == ""

    def test_no_se_pasa_del_largo(self):
        from app.utils.progress_bar import build_form_bar

        barra = build_form_bar(20, 10, length=10)
        assert barra.count(_FILLED) == 10

    def test_mismo_largo_que_la_barra_en_vivo(self):
        """Para que las dos queden alineadas en la misma lista."""
        from app.utils.progress_bar import build_form_bar

        forma = build_form_bar(8, 10, length=12)
        vivo = build_progress_bar(3, 3.5, length=12)
        assert forma.count(_FILLED) + forma.count(_EMPTY) == 12
        assert vivo.count(_FILLED) + vivo.count(_EMPTY) == 12


class TestNombreConTildes:
    """Bug real: la captura decía 'Luis Arraez' (la IA suele perder
    tildes) pero la MLB Stats API devuelve 'Luis Arráez' en el
    boxscore. El match era comparación literal -> no lo encontraba ->
    ProbabilityError -> la web caía al fallback histórico aunque el
    partido estuviera en vivo y el resto de las legs del mismo partido
    sí mostraran datos en vivo."""

    def _box(self):
        return {
            "Luis Arráez": {
                "player_id": 1,
                "is_current_batter": False,
                "batting_order": "3",
                "is_on_bench": False,
                "batting": {"hits": 1, "runs": 1, "rbi": 0},
                "pitching": {},
            }
        }

    def _track(self, player_leg_name):
        from unittest.mock import patch

        from app.analysis.live_tracking import track_leg_live

        with patch(
            "app.analysis.live_tracking.search_player",
            return_value={"id": 1, "full_name": "Luis Arráez", "position": "Hitter"},
        ):
            return track_leg_live(
                {"player": player_leg_name, "market": "Hits + Runs + RBIs", "line": "Over 0.5"},
                self._box(),
                {"inning": 5, "inning_state": "Bottom", "status": "In Progress"},
            )

    def test_encuentra_al_jugador_sin_tilde_en_la_leg(self):
        status = self._track("Luis Arraez")
        assert status.player == "Luis Arráez"
        assert status.already_hit is True

    def test_encuentra_al_jugador_con_tilde_en_la_leg(self):
        """No romper el caso en que la captura sí trae la tilde."""
        status = self._track("Luis Arráez")
        assert status.already_hit is True


class TestMercadosUnder:
    """Bug serio: en un Under, `current < threshold` es cierto desde el
    primer lanzamiento (0 ponches ya es 'menos de 5.5'), así que la leg
    se mostraba como ✅ CUMPLIDA cuando en realidad no está definida
    hasta que termina el partido."""

    def _box(self, strikeouts=2):
        return {
            "P": {
                "player_id": 1,
                "is_team_last_pitcher": True,
                "is_current_pitcher": True,
                "batting": {},
                "pitching": {"strikeouts": strikeouts, "outs": 9, "walks": 1, "hits_allowed": 3},
            }
        }

    def _track(self, line, status):
        from unittest.mock import patch

        from app.analysis.live_tracking import track_leg_live

        with patch(
            "app.analysis.live_tracking.search_player",
            return_value={"id": 1, "full_name": "P", "position": "Pitcher"},
        ), patch("app.analysis.live_tracking._recent_avg_rate", return_value=1.0):
            return track_leg_live(
                {"player": "P", "market": "Strikeouts", "line": line},
                self._box(),
                {"inning": 4, "inning_state": "Top", "status": status},
            )

    def test_under_no_se_marca_cumplida_con_partido_en_curso(self):
        assert self._track("Under 5.5", "In Progress").already_hit is False

    def test_under_se_marca_cumplida_recien_al_terminar(self):
        assert self._track("Under 5.5", "Final").already_hit is True

    def test_under_muestra_el_valor_actual(self):
        """Sin saber cuánto lleva, el % de mantenerse no dice nada."""
        assert "va 2" in self._track("Under 5.5", "In Progress").status_text

    def test_over_superado_se_marca_asegurada(self):
        """Un Over no puede revertirse: las estadísticas solo suben."""
        s = self._track("Over 1.5", "In Progress")
        assert s.already_hit is True
        assert "ASEGURADA" in s.status_text


class TestMercadoRunsDePitcher:
    """'Runs Over 1.5' en una prop de pitcher son las carreras que
    PERMITE. Quedaba sin reconocer y la leg no se analizaba."""

    def test_runs_en_ingles(self):
        from app.analysis.probability import _classify_pitcher_market

        assert _classify_pitcher_market("Runs") == ["earned_runs"]

    def test_carreras_conseguidas(self):
        from app.analysis.probability import _classify_pitcher_market

        assert _classify_pitcher_market("Carreras Conseguidas") == ["earned_runs"]

    def test_no_confunde_con_hits_permitidos(self):
        from app.analysis.probability import _classify_pitcher_market

        assert _classify_pitcher_market("Hits Allowed") == ["hits_allowed"]


class TestBarraDeFormaNoConfunde:
    """'2/10' al lado de una línea 'Over 0.5' se leía como si el objetivo
    fuera 10. Ahora dice '2 de 10' y va etiquetada como Forma."""

    def test_no_usa_formato_de_fraccion(self):
        from app.utils.progress_bar import build_form_bar

        barra = build_form_bar(8, 10)
        assert "8/10" not in barra
        assert "8 de 10" in barra

    def test_la_barra_en_vivo_si_muestra_el_objetivo(self):
        assert build_progress_bar(3, 3.5).endswith(" 4")


class TestHoraLocal:
    """Los horarios venían en UTC pese a tener la zona configurada:
    obligaba a hacer la cuenta mental en cada consulta."""

    def test_convierte_a_hora_argentina(self):
        from app.utils.tiempo import formato_hora

        # 23:40 UTC = 20:40 en Argentina (UTC-3)
        assert formato_hora("2026-07-28T23:40:00Z") == "20:40"

    def test_sin_dato_no_rompe(self):
        from app.utils.tiempo import formato_hora

        assert formato_hora(None) == "Hora TBD"

    def test_dato_invalido_no_rompe(self):
        from app.utils.tiempo import formato_hora

        assert formato_hora("no-es-una-fecha") == "Hora TBD"


class TestPartidosVigentes:
    """No tiene sentido sugerir picks de partidos ya jugados, y The Odds
    API a veces devuelve eventos viejos todavía en la lista."""

    def _iso(self, horas: float) -> str:
        from datetime import datetime, timedelta, timezone

        return (datetime.now(timezone.utc) + timedelta(hours=horas)).isoformat()

    def test_partido_futuro_es_vigente(self):
        from app.utils.tiempo import evento_vigente

        assert evento_vigente(self._iso(2)) is True

    def test_partido_en_curso_es_vigente(self):
        from app.utils.tiempo import evento_vigente

        assert evento_vigente(self._iso(-1)) is True

    def test_partido_terminado_no_es_vigente(self):
        from app.utils.tiempo import evento_vigente

        assert evento_vigente(self._iso(-6)) is False

    def test_partido_de_ayer_no_es_vigente(self):
        from app.utils.tiempo import evento_vigente

        assert evento_vigente(self._iso(-24)) is False

    def test_sin_horario_no_es_vigente(self):
        from app.utils.tiempo import evento_vigente

        assert evento_vigente(None) is False


class TestAbreviaturasDeEquipo:
    """Telegram no permite imágenes dentro del texto, así que la
    identificación visual se hace con la abreviatura oficial."""

    def test_equipos_conocidos(self):
        from app.utils.equipos import abreviatura

        assert abreviatura("New York Yankees") == "NYY"
        assert abreviatura("Los Angeles Dodgers") == "LAD"

    def test_partido_completo(self):
        from app.utils.equipos import abreviar_partido

        assert abreviar_partido("New York Yankees @ Boston Red Sox") == "NYY @ BOS"

    def test_soporta_separador_con_guion(self):
        from app.utils.equipos import abreviar_partido

        assert abreviar_partido("Texas Rangers - Seattle Mariners") == "TEX @ SEA"

    def test_equipo_desconocido_no_rompe(self):
        from app.utils.equipos import abreviatura

        assert abreviatura("Equipo Inventado FC") == "EIF"

    def test_url_de_logo(self):
        from app.utils.equipos import url_logo

        assert url_logo("New York Yankees").endswith("/147.svg")


class TestNombresDeMercadoStake:
    """Decir 'Hits' no sirve si en la app dice 'Golpes'."""

    def test_traduce_a_como_lo_muestra_stake(self):
        from app.utils.market_labels import nombre_stake

        assert nombre_stake("batter_hits") == "Hits"
        assert nombre_stake("pitcher_outs") == "Salidas del Campo"
        assert nombre_stake("batter_hits_runs_rbis") == "Golpes + Carreras + Carreras Remolcadas (RBIs)"

    def test_mercado_desconocido_no_rompe(self):
        from app.utils.market_labels import nombre_stake

        assert nombre_stake("algo_raro") == "Algo Raro"


class TestPartidoTerminado:
    """Al terminar el partido hay que CONSERVAR cómo quedó el ticket.
    Antes se volvía al promedio histórico y se perdía el resultado."""

    def _box(self, hits):
        return {"B": {
            "player_id": 1, "is_team_last_pitcher": True, "batting_order": "100",
            "batting": {"hits": hits, "runs": 0, "rbi": 0, "home_runs": 0,
                        "strikeouts": 0, "walks": 0, "stolen_bases": 0},
            "pitching": {},
        }}

    def _track(self, hits, line, status):
        from unittest.mock import patch

        from app.analysis.live_tracking import track_leg_live

        with patch("app.analysis.live_tracking.search_player",
                   return_value={"id": 1, "full_name": "B", "position": "Infielder"}), \
             patch("app.analysis.live_tracking._recent_avg_rate", return_value=1.0):
            return track_leg_live(
                {"player": "B", "market": "Hits", "line": line},
                self._box(hits),
                {"inning": 9, "inning_state": "End", "status": status},
            )

    def test_no_cumplida_con_partido_final_queda_perdida(self):
        s = self._track(0, "Over 0.5", "Final")
        assert s.perdida is True
        assert s.already_hit is False
        assert "NO SE DIO" in s.status_text

    def test_en_curso_no_se_da_por_perdida(self):
        """Con el partido abierto todavía puede darse: no es un resultado."""
        s = self._track(0, "Over 0.5", "In Progress")
        assert s.perdida is False
        assert "%" in s.status_text

    def test_cumplida_con_partido_final(self):
        s = self._track(2, "Over 0.5", "Final")
        assert s.already_hit is True
        assert s.perdida is False

    def test_game_over_tambien_cuenta_como_terminado(self):
        assert self._track(0, "Over 0.5", "Game Over").perdida is True

    def test_la_web_traduce_perdida_a_lost(self):
        from app.web.service import _estado_leg

        assert _estado_leg(self._track(0, "Over 0.5", "Final")) == "lost"
        assert _estado_leg(self._track(2, "Over 0.5", "Final")) == "done"
