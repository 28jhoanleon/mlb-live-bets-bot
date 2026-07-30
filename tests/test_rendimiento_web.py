"""Bug real reportado: la página seguía tardando mucho aunque el
endpoint ya no bloqueaba el event loop compartido con el bot. La causa
que faltaba: dentro de UN mismo pedido, cada leg que caía al histórico
se procesaba una por una (2 llamadas de red bloqueantes cada una). Con
varias legs sin partido arrancado, el tiempo total era la SUMA de
todas. Ahora se procesan en paralelo con un thread pool: el tiempo
total tiene que acercarse al de la más lenta, no a la suma."""
import time
from unittest.mock import patch

from app.web.service import _armar_grupo

_DEMORA = 0.2  # cada "llamada de red" simulada tarda esto


def _estimate_lenta(player, market, line):
    time.sleep(_DEMORA)
    from app.analysis.probability import LegEstimate

    return LegEstimate(
        player=player, market=market, side="Over", threshold=0.5,
        probability_pct=70.0, sample_size=10, avg_value=1.5, is_pitcher=False,
    )


class TestLegsHistoricasEnParalelo:
    def test_varias_legs_historicas_no_se_suman_en_serie(self):
        legs = [
            {"player": f"Jugador {i}", "market": "Hits", "line": "Over 0.5", "match": "A @ B"}
            for i in range(6)
        ]

        with patch("app.web.service.buscar_partido", return_value=None), \
             patch("app.web.service.estimate_leg_probability", side_effect=_estimate_lenta):
            inicio = time.perf_counter()
            grupo = _armar_grupo("A @ B", legs)
            duracion = time.perf_counter() - inicio

        assert len(grupo["legs"]) == 6
        # En serie: 6 * 0.2s = 1.2s. En paralelo (8 workers): ~0.2-0.4s.
        # Damos margen generoso para no ser flaky en CI lento.
        assert duracion < _DEMORA * 3, (
            f"tardó {duracion:.2f}s -- parece estar procesando las legs "
            f"históricas en fila, no en paralelo"
        )
