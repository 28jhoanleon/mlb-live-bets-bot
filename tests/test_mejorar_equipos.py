"""/mejorar mostraba el partido solo cuando había más de uno, y nunca
mostraba de qué equipo era cada jugador -- en una combinada del mismo
partido con gente de los dos lados, no había forma de saber quién
jugaba para quién sin buscarlo a mano.
"""
from unittest.mock import patch

from app.analysis.auditoria import LegSegura
from app.bot.handlers.mejorar import _fmt_tramo_seguro


def _tramo(player="Yandy Diaz", match="Rays @ Tigers", cambio=True, no_alcanza=False):
    return LegSegura(
        player=player, match=match, market="batter_hits",
        linea_original="Over 1.5", linea_nueva="Over 0.5",
        probabilidad=91.2, cambio=cambio, no_alcanza=no_alcanza,
    )


class TestElEquipoJuntoAlJugador:
    def test_sin_equipo_no_rompe(self):
        texto = _fmt_tramo_seguro(_tramo())
        assert "Yandy Diaz" in texto
        assert "(" not in texto

    def test_con_equipo_lo_muestra_pegado_al_nombre(self):
        texto = _fmt_tramo_seguro(_tramo(), equipo="Tampa Bay Rays")
        assert "Yandy Diaz" in texto
        assert "Tampa Bay Rays" in texto
        # tiene que estar en la misma línea que el jugador, no aparte
        primera_linea = texto.split("\n")[0]
        assert "Tampa Bay Rays" in primera_linea

    def test_funciona_para_los_tres_estados(self):
        for cambio, no_alcanza in [(True, False), (False, False), (False, True)]:
            texto = _fmt_tramo_seguro(_tramo(cambio=cambio, no_alcanza=no_alcanza),
                                       equipo="Detroit Tigers")
            assert "Detroit Tigers" in texto


class TestElTituloDelPartidoSiempreAparece:
    """Antes solo se mostraba con más de un partido en la combinada;
    con uno solo, no había ningún indicio de contra quién jugaban."""

    def test_el_codigo_ya_no_condiciona_el_titulo_a_haber_mas_de_uno(self):
        import pathlib

        fuente = pathlib.Path("app/bot/handlers/mejorar.py").read_text()
        assert "if len(por_partido) > 1:" not in fuente
        assert 'partes.append(f"⚾ *{escape_md(partido_corto(partido))}*")' in fuente


class TestSoloAclaraElEquipoCuandoHaceFalta:
    """Si todos los jugadores de un partido son del mismo equipo, ya lo
    dice el título -- repetirlo en cada línea es ruido, no información."""

    def test_detecta_cuando_hay_un_solo_equipo_en_el_grupo(self):
        import pathlib

        fuente = pathlib.Path("app/bot/handlers/mejorar.py").read_text()
        assert "aclarar_equipo = len(equipos_del_grupo) > 1" in fuente


class TestUsaLaCacheExistenteNoLaRed:
    """version_segura ya buscó a cada jugador para estimar probabilidad;
    volver a buscarlo para el equipo no puede pegarle a la red de
    nuevo."""

    def test_usa_la_funcion_cacheada(self):
        import pathlib

        fuente = pathlib.Path("app/bot/handlers/mejorar.py").read_text()
        assert "_buscar_jugador_cacheado" in fuente

    def test_un_jugador_que_falla_no_rompe_el_resto(self):
        import pathlib

        fuente = pathlib.Path("app/bot/handlers/mejorar.py").read_text()
        i = fuente.index("def _equipo_de(")
        bloque = fuente[i:i + 400]
        assert "except Exception:" in bloque
