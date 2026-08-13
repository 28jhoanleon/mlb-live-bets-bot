"""Ningún módulo debe quedar escrito y sin conectar.

Este proyecto ya tuvo cuatro casos del mismo patrón: `hoy_local` sin
usar, `remove_vig` sin llamar, dos módulos de estadísticas de equipo
(`team_stats` y `equipos_stats`), y `matchup.py` duplicando a
`pitcher_rival.py`. Todos parecían inofensivos y todos costaron horas:
el código muerto se desincroniza del vivo y después alguien lo lee
creyendo que es la verdad.
"""
import pathlib
import re

RAIZ = pathlib.Path(__file__).resolve().parent.parent
APP = RAIZ / "app"

_PERMITIDOS = {"__init__", "config", "logger"}


def _modulos():
    for archivo in APP.rglob("*.py"):
        if "__pycache__" in archivo.parts or archivo.stem in _PERMITIDOS:
            continue
        yield archivo


def _todo_el_codigo():
    partes = []
    for carpeta in (APP, RAIZ / "tests"):
        for archivo in carpeta.rglob("*.py"):
            if "__pycache__" not in archivo.parts:
                partes.append(archivo.read_text(encoding="utf-8"))
    partes.append((RAIZ / "main.py").read_text(encoding="utf-8"))
    return "\n".join(partes)


def _esta_importado(archivo, codigo):
    """¿Alguien lo importa de verdad? Mencionarlo en un comentario no
    cuenta como usarlo."""
    ruta = archivo.relative_to(APP).with_suffix("")
    punteada = re.escape(".".join(ruta.parts))
    paquete = re.escape(".".join(ruta.parts[:-1]))
    nombre = re.escape(archivo.stem)

    patrones = [
        r"from app\." + punteada + r" import",
        r"import app\." + punteada + r"\b",
        # Import agrupado, que puede ocupar varias líneas:
        #   from app.bot.handlers import (
        #       analyze,
        #       borrar,
        #   )
        r"from app\." + paquete + r" import \([^)]*\b" + nombre + r"\b",
        r"from app\." + paquete + r" import [^\n]*\b" + nombre + r"\b",
        r"app\." + punteada + r"\.",
    ]
    return any(re.search(pat, codigo) for pat in patrones)


class TestSinModulosHuerfanos:
    def test_todos_los_modulos_se_usan(self):
        codigo = _todo_el_codigo()
        huerfanos = [
            str(a.relative_to(RAIZ)) for a in _modulos()
            if not _esta_importado(a, codigo)
        ]
        assert not huerfanos, (
            f"módulos escritos y nunca conectados: {huerfanos}. "
            "O se usan, o se borran: dejarlos ahí garantiza que se "
            "desincronicen del código vivo."
        )

    def test_no_hay_dos_modulos_de_pitcher_rival(self):
        """El caso concreto: matchup.py duplicaba pitcher_rival.py."""
        candidatos = [
            a.stem for a in _modulos()
            if "whip" in a.read_text(encoding="utf-8").lower()
        ]
        assert len(candidatos) <= 1, (
            f"más de un módulo calcula lo mismo sobre el pitcher rival: {candidatos}"
        )
