"""El partido no está "en vivo" 20 minutos antes de empezar.

La MLB marca el estado "Warmup" cuando los equipos salen a calentar,
unos 20 minutos antes del primer lanzamiento. Ese estado estaba dentro
de EN_CURSO, así que la web mostraba el partido como si ya se estuviera
jugando y buscaba datos en vivo que todavía no existen.

"Delayed" tampoco es en curso: es una demora, no juego.
"""
from app.mlb.estados import CON_DATOS, EN_CURSO, POR_EMPEZAR, TERMINADO


class TestWarmupNoEsEnVivo:
    def test_warmup_quedo_afuera_de_en_curso(self):
        assert "Warmup" not in EN_CURSO

    def test_delayed_tampoco(self):
        assert "Delayed" not in EN_CURSO

    def test_lo_que_si_es_en_curso(self):
        assert "In Progress" in EN_CURSO

    def test_warmup_esta_en_la_antesala(self):
        """Se distingue de "Scheduled" para poder avisar que falta poco
        sin mentir diciendo que ya empezó."""
        assert "Warmup" in POR_EMPEZAR
        assert "Delayed" in POR_EMPEZAR

    def test_los_estados_no_se_solapan(self):
        assert not set(EN_CURSO) & set(POR_EMPEZAR)
        assert not set(EN_CURSO) & set(TERMINADO)
        assert not set(POR_EMPEZAR) & set(TERMINADO)


class TestNoSeBuscanDatosQueNoExisten:
    def test_un_partido_en_warmup_no_tiene_boxscore_que_pedir(self):
        """Antes se le pedía el estado en vivo a un partido que no
        empezó: no hay nada que traer."""
        assert "Warmup" not in CON_DATOS

    def test_los_terminados_si_tienen_datos(self):
        assert "Final" in CON_DATOS


class TestSeAvisaEnLaWeb:
    def test_el_grupo_expone_por_empezar(self):
        import pathlib

        fuente = pathlib.Path("app/web/service.py").read_text()
        assert '"por_empezar"' in fuente

    def test_la_web_lo_muestra(self):
        import pathlib

        html = pathlib.Path("app/web/static/index.html").read_text()
        assert "Por empezar" in html
