"""El barrido de picks tiene que sobrevivir a fallos puntuales.

Bug real: al ampliar de 3 a 15 mercados y de 5 a 12 partidos, el mismo
jugador aparecía en hasta 10 props distintos y cada uno repetía las dos
llamadas a la MLB API. Eso multiplicó el tráfico, la API empezó a
cortar, y como find_daily_picks sólo atrapaba ProbabilityError, un
error de red burbujeaba hasta el handler: /sonadoras terminaba con
"error inesperado" sin devolver nada.
"""
from unittest.mock import patch

from app.analysis import daily_picks as dp
from app.analysis import probability as prob
from app.analysis.probability import LegEstimate, ProbabilityError


def _payload(jugadores, mercados):
    return {"bookmakers": [{"title": "Stake", "markets": [
        {"key": m, "outcomes": [
            {"description": j, "name": "Over", "point": 0.5, "price": 1.45}
            for j in jugadores
        ]} for m in mercados
    ]}]}


def _est(nombre):
    return LegEstimate(player=nombre, market="Hits", side="Over", threshold=0.5,
                       probability_pct=80.0, sample_size=10, avg_value=1.5,
                       is_pitcher=False)


class TestUnFalloNoTumbaElBarrido:
    def test_un_error_de_red_en_un_prop_no_corta_todo(self):
        eventos = [{"id": "1", "away_team": "A", "home_team": "B",
                    "commence_time": "2099-01-01T00:00:00Z"}]

        def _estimador(player, market, line):
            if player == "Explota":
                raise ConnectionError("la MLB API cortó")
            return _est(player)

        with patch("app.odds.parlay.hay_clave", return_value=False), \
             patch("app.odds.theodds.get_events", return_value=eventos), \
             patch("app.odds.theodds.get_player_props",
                   return_value=_payload(["Bueno", "Explota", "Otro"], ["batter_hits"])), \
             patch.object(dp, "estimate_leg_probability", side_effect=_estimador), \
             patch.object(dp, "evento_vigente", return_value=True):
            picks = dp.find_daily_picks()

        nombres = {p.player for p in picks}
        assert "Bueno" in nombres and "Otro" in nombres, (
            "un solo prop fallado se llevó puesto todo el barrido"
        )
        assert "Explota" not in nombres

    def test_probability_error_sigue_descartando_el_prop(self):
        eventos = [{"id": "1", "away_team": "A", "home_team": "B",
                    "commence_time": "2099-01-01T00:00:00Z"}]

        def _estimador(player, market, line):
            if player == "Desconocido":
                raise ProbabilityError("no está en el roster")
            return _est(player)

        with patch("app.odds.parlay.hay_clave", return_value=False), \
             patch("app.odds.theodds.get_events", return_value=eventos), \
             patch("app.odds.theodds.get_player_props",
                   return_value=_payload(["Bueno", "Desconocido"], ["batter_hits"])), \
             patch.object(dp, "estimate_leg_probability", side_effect=_estimador), \
             patch.object(dp, "evento_vigente", return_value=True):
            picks = dp.find_daily_picks()

        assert {p.player for p in picks} == {"Bueno"}


class TestCacheDeEstimaciones:
    def test_no_repite_la_busqueda_del_mismo_jugador(self):
        """Aaron Judge aparece en 10 mercados: tiene que buscarse UNA vez."""
        prob.limpiar_cache_estimaciones()
        mercados = ["batter_hits", "batter_rbis", "batter_total_bases",
                    "batter_runs_scored", "batter_home_runs"]

        with patch.object(prob, "search_player",
                          return_value={"id": 1, "full_name": "Aaron Judge",
                                        "position": "Hitter"}) as buscar, \
             patch.object(prob, "get_recent_hitting_games",
                          return_value=[{"date": "2026-08-01", "hits": 2, "runs": 1,
                                         "rbi": 1, "total_bases": 3, "home_runs": 0}
                                        for _ in range(10)]) as juegos:
            for m in mercados:
                prob.estimate_leg_probability("Aaron Judge", m, "Over 0.5")

        assert buscar.call_count == 1, (
            f"buscó al jugador {buscar.call_count} veces para {len(mercados)} mercados"
        )
        assert juegos.call_count == 1

    def test_limpiar_cache_fuerza_a_recargar(self):
        """Entre barridos hay que releer: los datos cambian."""
        prob.limpiar_cache_estimaciones()
        with patch.object(prob, "search_player",
                          return_value={"id": 1, "full_name": "X", "position": "Hitter"}) as buscar, \
             patch.object(prob, "get_recent_hitting_games",
                          return_value=[{"date": "2026-08-01", "hits": 1} for _ in range(10)]):
            prob.estimate_leg_probability("X", "batter_hits", "Over 0.5")
            prob.limpiar_cache_estimaciones()
            prob.estimate_leg_probability("X", "batter_hits", "Over 0.5")

        assert buscar.call_count == 2


class TestTodosLosMercadosSeReconocen:
    def test_ningun_mercado_pedido_queda_sin_clasificar(self):
        """batter_home_runs y batter_total_bases fallaban por el guión
        bajo: "home run" no matcheaba contra "batter_home_runs". Home
        runs era uno de los tres mercados originales, así que llevaba
        roto desde el principio sin que nada avisara."""
        from app.odds.theodds import MERCADOS_SOPORTADOS

        fallan = []
        for clave in MERCADOS_SOPORTADOS.split(","):
            clasificar = (prob._classify_pitcher_market
                          if clave.startswith("pitcher")
                          else prob._classify_batter_market)
            try:
                clasificar(clave)
            except ProbabilityError:
                fallan.append(clave)

        assert not fallan, f"mercados pedidos que no sabemos evaluar: {fallan}"


class TestPrecalentadoParalelo:
    """Bug real: /mejorar quedó 11 minutos en "Revisando tus tramos...".
    La causa era que las ~430 llamadas a la MLB API se hacían de a una,
    encadenadas. Precalentando en paralelo, el tiempo total pasa a ser
    el de la llamada más lenta y no la suma de todas."""

    def test_las_llamadas_no_se_encadenan(self):
        import time

        LATENCIA = 0.05
        nombres = [f"Jugador {i}" for i in range(20)]

        def _buscar(n):
            time.sleep(LATENCIA)
            return {"id": abs(hash(n)) % 9999, "full_name": n, "position": "Hitter"}

        def _juegos(pid, last_n=10):
            time.sleep(LATENCIA)
            return [{"date": "2026-08-01", "hits": 1} for _ in range(10)]

        prob.limpiar_cache_estimaciones()
        with patch.object(prob, "search_player", side_effect=_buscar), \
             patch.object(prob, "get_recent_hitting_games", side_effect=_juegos):
            inicio = time.perf_counter()
            prob.precalentar_cache(nombres)
            duracion = time.perf_counter() - inicio

        # En serie: 20 jugadores × 2 llamadas × 0.05s = 2s.
        # En paralelo con 12 hilos: bastante menos. Margen amplio para no
        # ser flaky en un runner lento.
        assert duracion < 1.0, (
            f"tardó {duracion:.2f}s -- parece estar encadenando las llamadas"
        )

    def test_despues_de_precalentar_no_se_toca_la_red(self):
        """Lo que hace que valga la pena: el bucle que sigue son todos
        aciertos de caché."""
        prob.limpiar_cache_estimaciones()
        with patch.object(prob, "search_player",
                          return_value={"id": 1, "full_name": "X", "position": "Hitter"}), \
             patch.object(prob, "get_recent_hitting_games",
                          return_value=[{"date": "2026-08-01", "hits": 1} for _ in range(10)]):
            prob.precalentar_cache(["X"])

        # Ya cacheado: si volviera a la red, estos mocks explotarían.
        def _explota(*a, **k):
            raise AssertionError("volvió a pegarle a la red pese al precalentado")

        with patch.object(prob, "search_player", side_effect=_explota), \
             patch.object(prob, "get_recent_hitting_games", side_effect=_explota):
            est = prob.estimate_leg_probability("X", "batter_hits", "Over 0.5")
        assert est.player == "X"

    def test_un_jugador_que_falla_no_frena_el_precalentado(self):
        def _buscar(n):
            if n == "Explota":
                raise ConnectionError("cortó")
            return {"id": 1, "full_name": n, "position": "Hitter"}

        prob.limpiar_cache_estimaciones()
        with patch.object(prob, "search_player", side_effect=_buscar), \
             patch.object(prob, "get_recent_hitting_games",
                          return_value=[{"date": "2026-08-01", "hits": 1} for _ in range(10)]):
            prob.precalentar_cache(["Bueno", "Explota", "Otro"])  # no debe levantar
