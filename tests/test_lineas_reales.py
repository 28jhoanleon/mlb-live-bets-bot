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


class TestTechoRelativoNoEnPuntos:
    """El techo de ventaja se medía en PUNTOS de diferencia y por eso no
    frenaba nada. Caso real de la captura: nuestra estimación 76.9%
    contra un mercado que paga 43.5% son 33 puntos -- pasaba el filtro
    de 40-- pero es un 77% de ventaja relativa. Al multiplicar cuatro
    legs así, el valor del combo daba +389%.
    """

    def _relativo(self, nuestra_pct, cuota):
        mercado = 100 / cuota
        return (nuestra_pct - mercado) / mercado * 100

    def test_el_caso_de_la_captura_se_descarta(self):
        assert self._relativo(76.9, 2.3) > _EDGE_MAXIMO_CREIBLE

    def test_una_ventaja_moderada_sigue_pasando(self):
        """No queremos filtrar de más: un edge chico y creíble tiene que
        sobrevivir, si no nunca sale ninguna soñadora."""
        assert self._relativo(50.0, 2.5) < _EDGE_MAXIMO_CREIBLE

    def test_medido_en_puntos_el_filtro_no_servia(self):
        """Demuestra por qué había que cambiar la medida."""
        en_puntos = 76.9 - (100 / 2.3)
        assert en_puntos < _EDGE_MAXIMO_CREIBLE, (
            "en puntos el caso roto pasaba el filtro: por eso se mide "
            "en proporción"
        )


class TestTechoDelCombo:
    def test_hay_techo_para_el_valor_esperado(self):
        from app.analysis.combos import _EV_MAXIMO_CREIBLE

        assert _EV_MAXIMO_CREIBLE > 0

    def test_los_valores_rotos_quedan_afuera(self):
        """Las soñadoras mostraban +389%, +373% y +504%: un combo que
        promete multiplicar por cinco lo apostado EN PROMEDIO no es una
        oportunidad, es error acumulado."""
        from app.analysis.combos import _EV_MAXIMO_CREIBLE

        for ev_roto in (389.2, 373.0, 504.6, 13862.6):
            assert ev_roto > _EV_MAXIMO_CREIBLE
