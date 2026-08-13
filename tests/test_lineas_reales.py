"""Sugerir solamente líneas que la casa realmente ofrece.

Stake publica para un abridor: Strikeouts desde 1.5, Golpes Permitidos
desde 2.5, Carreras Conseguidas desde 2.5. NO existe "Golpes Permitidos
Over 0.5". El bot las venía sugiriendo igual: inútiles aunque el cálculo
fuera correcto, porque no se pueden jugar.

Y son justo las que disparan ventajas falsas: una línea tan baja da ~96%
de probabilidad, y comparada contra cualquier precio parece una
oportunidad histórica.
"""
from app.analysis.daily_picks import (
    _EDGE_MAXIMO_CREIBLE,
    _LINEA_MINIMA,
    _linea_existe,
)


class TestLineasQueExisten:
    def test_rechaza_golpes_permitidos_en_medio(self):
        """El caso de la captura: Stake arranca en 2.5."""
        assert not _linea_existe("pitcher_hits_allowed", 0.5)
        assert not _linea_existe("pitcher_hits_allowed", 1.5)
        assert _linea_existe("pitcher_hits_allowed", 2.5)

    def test_rechaza_strikeouts_de_pitcher_muy_bajos(self):
        assert not _linea_existe("pitcher_strikeouts", 0.5)
        assert _linea_existe("pitcher_strikeouts", 1.5)
        assert _linea_existe("pitcher_strikeouts", 4.5)

    def test_los_mercados_de_bateo_si_tienen_medio(self):
        """Un bateador sí tiene Over 0.5 en hits, carreras y RBIs."""
        for mercado in ("batter_hits", "batter_runs_scored",
                        "batter_rbis", "batter_hits_runs_rbis"):
            assert _linea_existe(mercado, 0.5), mercado

    def test_un_mercado_sin_regla_no_se_bloquea(self):
        """Ante la duda, dejar pasar: perder un pick es peor que
        bloquear de más sin motivo."""
        assert _linea_existe("mercado_nuevo", 0.5)

    def test_sin_linea_no_se_bloquea(self):
        assert _linea_existe("pitcher_hits_allowed", None)

    def test_las_salidas_del_campo_empiezan_alto(self):
        """Un abridor registra 15-18 outs: una línea de 0.5 no existe."""
        assert not _linea_existe("pitcher_outs", 0.5)
        assert _linea_existe("pitcher_outs", 14.5)


class TestTechoDeVentaja:
    def test_hay_un_techo_configurado(self):
        assert _EDGE_MAXIMO_CREIBLE > 0

    def test_el_techo_es_exigente_pero_no_absurdo(self):
        """Un edge real contra una casa rara vez pasa el 20-30%. Más
        arriba de eso, es un problema de datos: línea inexistente,
        precio simbólico de una app DFS, o mercado mal interpretado.
        Todos los bugs de esta semana se vieron como ventajas absurdas."""
        assert 20 <= _EDGE_MAXIMO_CREIBLE <= 60

    def test_cubre_los_casos_reales_que_fallaron(self):
        """Las soñadoras rotas mostraban +13862% y +2077%."""
        for edge_falso in (13862.6, 2077.1, 120.0):
            assert edge_falso > _EDGE_MAXIMO_CREIBLE


class TestCoberturaDeMercadosDePitcheo:
    def test_todos_los_mercados_de_pitcheo_tienen_minimo(self):
        """Si se agrega un mercado de pitcheo sin mínimo, vuelve el bug
        de sugerir líneas que no existen."""
        from app.odds.parlay import _MERCADOS_PITCHEO

        faltantes = [m for m in _MERCADOS_PITCHEO.values() if m not in _LINEA_MINIMA]
        assert not faltantes, f"mercados de pitcheo sin línea mínima: {faltantes}"
