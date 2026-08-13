"""Bug real: un cupón de 11 selecciones no se podía leer.

El bot decía "probá con imágenes más nítidas", pero la imagen estaba
perfecta. El límite de tokens de la respuesta era 1000, y el JSON de 11
legs con todos los campos que pedimos ocupa ~1012: se cortaba justo por
la mitad, quedaba inválido, y el error genérico hacía parecer que era
un problema de calidad de imagen.
"""
import json
from unittest.mock import patch

import pytest

from app.ai import vision
from app.ai.vision import VisionAnalysisError


def _leg():
    return {
        "match": "Detroit Tigers vs Cleveland Guardians",
        "match_datetime": "2026-08-14 14:10",
        "player": "Spencer Torkelson", "ambito": "jugador", "team": None,
        "market": "Golpes + Carreras + Carreras Remolcadas (RBIs)",
        "line": "Over 0.5", "odds": None, "group_odds": "5.00",
    }


class TestLimiteDeTokens:
    def test_alcanza_para_un_cupon_grande(self):
        """El caso reportado tenía 11 selecciones."""
        import re
        import pathlib

        fuente = pathlib.Path("app/ai/vision.py").read_text()
        limite = int(re.search(r'"max_tokens":\s*(\d+)', fuente).group(1))

        json_11 = json.dumps(
            {"bets": [{"total_odds": "80.5", "legs": [_leg()] * 11}]},
            ensure_ascii=False,
        )
        tokens_estimados = len(json_11) // 3
        assert limite > tokens_estimados * 1.5, (
            f"límite {limite} demasiado justo para un cupón de 11 legs "
            f"(~{tokens_estimados} tokens): se va a cortar igual que antes"
        )


@pytest.fixture(autouse=True)
def _con_clave(monkeypatch):
    import dataclasses
    from app.config import settings
    monkeypatch.setattr(vision, "settings",
                        dataclasses.replace(settings, openai_api_key="sk-test"))


class TestRespuestaCortada:
    def _respuesta(self, finish_reason, contenido):
        return {"choices": [{
            "finish_reason": finish_reason,
            "message": {"content": contenido},
        }]}

    def test_avisa_que_se_corto_en_vez_de_culpar_a_la_imagen(self):
        """Distinguir los dos casos importa: "la foto está borrosa" y "el
        cupón no entra" se arreglan de formas distintas."""
        cortada = self._respuesta("length", '{"bets": [{"legs": [{"pla')

        with patch.object(vision.requests, "post") as post:
            post.return_value.json.return_value = cortada
            post.return_value.raise_for_status.return_value = None
            with pytest.raises(VisionAnalysisError) as e:
                vision.analyze_bet_screenshot(b"imagen")

        assert "largo" in str(e.value).lower()
        assert "nítid" not in str(e.value).lower()

    def test_una_respuesta_completa_se_parsea(self):
        buena = self._respuesta("stop", json.dumps({"bets": [{"legs": [_leg()]}]}))

        with patch.object(vision.requests, "post") as post:
            post.return_value.json.return_value = buena
            post.return_value.raise_for_status.return_value = None
            resultado = vision.analyze_bet_screenshot(b"imagen")

        assert len(resultado["bets"][0]["legs"]) == 1

    def test_json_envuelto_en_backticks_igual_se_lee(self):
        crudo = "```json\n" + json.dumps({"bets": []}) + "\n```"
        with patch.object(vision.requests, "post") as post:
            post.return_value.json.return_value = self._respuesta("stop", crudo)
            post.return_value.raise_for_status.return_value = None
            assert vision.analyze_bet_screenshot(b"imagen") == {"bets": []}
