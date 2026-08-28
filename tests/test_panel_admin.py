"""Panel de administración de fuentes en la web.

Antes, dejar de seguir una fuente vivía mezclado con los filtros de la
lista de mensajes, y solo aparecía si ya había más de una fuente CON
mensajes propios guardados. Una fuente recién seguida (por ejemplo, por
una reacción) no se veía en ningún lado hasta que le llegara algo. El
panel es independiente de eso.
"""
import pathlib

HTML = pathlib.Path("app/web/static/index.html").read_text()


class TestElPanelEsIndependienteDeLosMensajes:
    def test_se_carga_al_entrar_a_la_pestana(self):
        """renderPanelFuentes se llama SIEMPRE al abrir Grupo, no solo
        cuando hay mensajes."""
        i = HTML.index("async function cargarMensajes()")
        bloque = HTML[i:i + 400]
        assert "renderPanelFuentes()" in bloque

    def test_tiene_su_propio_endpoint_de_carga(self):
        assert "async function renderPanelFuentes()" in HTML
        assert "/api/fuentes" in HTML

    def test_muestra_algo_incluso_sin_fuentes(self):
        assert "No estás siguiendo ninguna fuente todavía" in HTML

    def test_muestra_algo_si_falla_la_carga(self):
        i = HTML.index("async function renderPanelFuentes()")
        bloque = HTML[i:i + 900]
        assert "No pude traer las fuentes" in bloque


class TestElPanelMuestraLosFiltros:
    def test_hay_una_funcion_que_los_describe(self):
        assert "function _describirFiltros(f)" in HTML

    def test_distingue_solo_apuestas_de_los_manuales(self):
        """solo_apuestas (auto, por reacción) y requiere_foto/requiere_link
        (manual, por /fuentes) son cosas distintas y se describen distinto."""
        i = HTML.index("function _describirFiltros(f)")
        bloque = HTML[i:i + 500]
        assert "solo_apuestas" in bloque
        assert "requiere_foto" in bloque
        assert "requiere_link" in bloque


class TestBotonDejarDeSeguir:
    def test_cada_fuente_tiene_su_boton(self):
        i = HTML.index("async function renderPanelFuentes()")
        j = HTML.index("function _describirFiltros")
        bloque = HTML[i:j]
        assert "dejarFuente(" in bloque
        assert "Dejar de seguir" in bloque

    def test_pide_confirmacion_antes_de_borrar(self):
        i = HTML.index("async function dejarFuente(")
        bloque = HTML[i:i + 300]
        assert "confirm(" in bloque


class TestNoQuedaronDuplicados:
    def test_una_sola_definicion_de_cada_funcion(self):
        import re

        for fn in ("cargarMensajes", "renderPanelFuentes", "dejarFuente",
                   "toggleFuentes", "borrarMensaje", "filtrarFuente", "enlazar"):
            n = len(re.findall(rf"function {fn}\(", HTML))
            assert n == 1, f"{fn} tiene {n} definiciones"


class TestTituloSegunOrigen:
    """Antes el título de cada fila era siempre el grupo, y el autor
    quedaba en letra chica abajo -- así que una fuente creada por
    reacción a una persona puntual parecía "seguir todo el grupo".
    Cuando viene de una reacción, lo que importa (el autor) va arriba."""

    def test_hay_logica_de_titulo_condicional(self):
        i = HTML.index("async function renderPanelFuentes()")
        j = HTML.index("function _describirFiltros")
        bloque = HTML[i:j]
        assert "porReaccion" in bloque
        assert "f.autores.split(" in bloque

    def test_marca_visualmente_que_vino_de_una_reaccion(self):
        i = HTML.index("async function renderPanelFuentes()")
        j = HTML.index("function _describirFiltros")
        bloque = HTML[i:j]
        assert "por reacción" in bloque
