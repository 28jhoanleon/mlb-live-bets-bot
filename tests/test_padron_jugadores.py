"""Respaldo cuando /people/search devuelve 403.

Ese endpoint de la MLB falla de forma intermitente (se vio en los logs
de producción). Y cuando falla se cae TODA la cadena: sin jugador no hay
equipo, sin equipo no se deduce el partido, sin partido no hay datos en
vivo. El síntoma era una apuesta de 10 tramos de 10 partidos distintos
mostrada como "1 partido · ? @ ?", sin marcar nada.

El padrón de la temporada es una sola llamada a otro endpoint y queda
en memoria.
"""
from unittest.mock import patch

from app.mlb import players


PADRON = {"people": [
    {"id": 1, "fullName": "Ceddanne Rafaela",
     "currentTeam": {"name": "Boston Red Sox"},
     "primaryPosition": {"type": "Outfielder"}},
    {"id": 2, "fullName": "Yandy Díaz",
     "currentTeam": {"name": "Tampa Bay Rays"},
     "primaryPosition": {"type": "Infielder"}},
]}


def _sin_search(path, params=None, **kw):
    if "people/search" in path:
        raise RuntimeError("403 Client Error: Forbidden")
    return PADRON


class TestRespaldoConSearchCaido:
    def setup_method(self):
        players.limpiar_padron()

    def teardown_method(self):
        players.limpiar_padron()

    def test_encuentra_al_jugador_igual(self):
        with patch.object(players, "get", side_effect=_sin_search):
            assert players.search_player("Ceddanne Rafaela")["team"] == "Boston Red Sox"

    def test_devuelve_el_equipo(self):
        """Es lo que hace falta para deducir el partido."""
        with patch.object(players, "get", side_effect=_sin_search):
            assert players.search_player("Yandy Díaz")["team"] == "Tampa Bay Rays"

    def test_tolera_la_falta_de_tilde(self):
        """La IA lee "Yandy Diaz" de la captura."""
        with patch.object(players, "get", side_effect=_sin_search):
            assert players.search_player("Yandy Diaz")["full_name"] == "Yandy Díaz"

    def test_un_jugador_inexistente_sigue_dando_none(self):
        """El respaldo no puede inventar jugadores."""
        with patch.object(players, "get", side_effect=_sin_search):
            assert players.search_player("Fulano Inventado") is None

    def test_el_padron_se_carga_una_sola_vez(self):
        llamadas = {"n": 0}

        def _contar(path, params=None, **kw):
            if "people/search" in path:
                raise RuntimeError("403")
            llamadas["n"] += 1
            return PADRON

        with patch.object(players, "get", side_effect=_contar):
            players.search_player("Ceddanne Rafaela")
            players.search_player("Yandy Díaz")
            players.search_player("Ceddanne Rafaela")

        assert llamadas["n"] == 1, f"bajó el padrón {llamadas['n']} veces"


class TestCaminoNormal:
    def setup_method(self):
        players.limpiar_padron()

    def test_si_search_anda_no_se_usa_el_padron(self):
        respuesta = {"people": [
            {"id": 9, "fullName": "Aaron Judge",
             "currentTeam": {"name": "New York Yankees"},
             "primaryPosition": {"type": "Outfielder"}},
        ]}

        def _ok(path, params=None, **kw):
            if "people/search" in path:
                return respuesta
            raise AssertionError("no debería haber pedido el padrón")

        with patch.object(players, "get", side_effect=_ok):
            assert players.search_player("Aaron Judge")["id"] == 9


class TestElEquipoSiempreLlega:
    """LA causa raíz de que las legs quedaran sin partido.

    /people/search encuentra al jugador pero NO devuelve su equipo si no
    se lo pide explícitamente. Y sin equipo se corta toda la cadena: no
    se puede deducir el partido, no hay datos en vivo, y la web muestra
    "? @ ?" con todo agrupado bajo un partido inexistente.

    Lo confirmó el diagnóstico en producción: paso 1 verde (jugador
    encontrado), paso 2 rojo ("la API no devolvió el equipo").
    """

    def setup_method(self):
        players.limpiar_padron()

    def teardown_method(self):
        players.limpiar_padron()

    def test_se_pide_el_equipo_en_la_busqueda(self):
        import pathlib

        fuente = pathlib.Path("app/mlb/players.py").read_text()
        assert '"hydrate": "currentTeam"' in fuente

    def test_si_la_busqueda_no_lo_trae_se_pide_la_ficha(self):
        """Segundo intento: la ficha individual siempre incluye el equipo."""
        def _get(path, params=None, **kw):
            if "people/search" in path:
                return {"people": [{"id": 650490, "fullName": "Yandy Díaz",
                                    "primaryPosition": {"type": "Infielder"}}]}
            if path.startswith("/people/"):
                return {"people": [{"id": 650490, "fullName": "Yandy Díaz",
                                    "currentTeam": {"name": "Tampa Bay Rays"},
                                    "primaryPosition": {"type": "Infielder"}}]}
            return {}

        with patch.object(players, "get", side_effect=_get):
            assert players.search_player("Yandy Diaz")["team"] == "Tampa Bay Rays"

    def test_si_la_busqueda_ya_lo_trae_no_se_pide_de_nuevo(self):
        """No gastar una llamada extra cuando el dato ya vino."""
        llamadas = {"fichas": 0}

        def _get(path, params=None, **kw):
            if "people/search" in path:
                return {"people": [{"id": 1, "fullName": "X",
                                    "currentTeam": {"name": "Boston Red Sox"},
                                    "primaryPosition": {"type": "Outfielder"}}]}
            llamadas["fichas"] += 1
            return {}

        with patch.object(players, "get", side_effect=_get):
            assert players.search_player("X")["team"] == "Boston Red Sox"
        assert llamadas["fichas"] == 0

    def test_si_la_ficha_tambien_falla_no_rompe(self):
        def _get(path, params=None, **kw):
            if "people/search" in path:
                return {"people": [{"id": 1, "fullName": "X",
                                    "primaryPosition": {"type": "Outfielder"}}]}
            raise ConnectionError("cortó")

        with patch.object(players, "get", side_effect=_get):
            resultado = players.search_player("X")
        assert resultado["full_name"] == "X"
        assert resultado["team"] is None
