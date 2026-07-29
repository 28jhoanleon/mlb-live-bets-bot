"""Tests de regresión para los dos bugs de formato de Telegram:

1. Un bloque suelto más largo que el límite hacía que el "split"
   devolviera igual un trozo de 5000 caracteres -> BadRequest.
2. Nombres con '*' o '_' venidos de la IA rompían el parseo de Markdown
   y Telegram descartaba el mensaje entero.
"""
from app.utils.telegram_helpers import SAFE_LEN, TELEGRAM_MAX_LEN, escape_md, split_message


class TestSplitMessage:
    def test_texto_corto_queda_en_un_solo_mensaje(self):
        assert split_message("hola") == ["hola"]

    def test_parte_por_bloques_sin_cortar_al_medio(self):
        bloque = "x" * 2000
        texto = f"{bloque}\n\n{bloque}\n\n{bloque}"
        chunks = split_message(texto)
        assert len(chunks) > 1
        for c in chunks:
            assert len(c) <= SAFE_LEN

    def test_bloque_unico_gigante_se_corta_a_la_fuerza(self):
        """Este era el bug: sin '\n\n' donde cortar, devolvía un chunk
        de 5000 caracteres que Telegram rechazaba."""
        texto = "X" * 5000
        chunks = split_message(texto)
        assert len(chunks) >= 2
        for c in chunks:
            assert len(c) <= SAFE_LEN
            assert len(c) <= TELEGRAM_MAX_LEN

    def test_ningun_chunk_supera_el_limite_de_telegram(self):
        texto = "\n\n".join("Y" * 4500 for _ in range(3))
        for c in split_message(texto):
            assert len(c) <= TELEGRAM_MAX_LEN


class TestEscapeMarkdown:
    def test_escapa_guion_bajo(self):
        assert escape_md("Hits_Runs") == "Hits\\_Runs"

    def test_escapa_asterisco(self):
        assert escape_md("Player *Star*") == "Player \\*Star\\*"

    def test_none_devuelve_string_vacio(self):
        assert escape_md(None) == ""

    def test_texto_normal_no_se_altera(self):
        assert escape_md("J.T. Realmuto") == "J.T. Realmuto"

    def test_nombre_conflictivo_queda_balanceado(self):
        """Un nombre con un solo '_' dejaba el Markdown desbalanceado."""
        escapado = escape_md("Team_A")
        # Ya no quedan '_' sin su barra de escape delante
        assert "\\_" in escapado
        assert escapado.count("_") == escapado.count("\\_")
