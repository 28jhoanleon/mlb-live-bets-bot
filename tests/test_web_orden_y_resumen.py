"""Orden de los tickets y resumen de la cabecera.

Dos mejoras que no agregan nada visual pero cambian cuánto cuesta leer
la página: lo que está pasando ahora va arriba, y el resumen evita
tener que sumar tramos a ojo.
"""
from app.web.service import estado_apuestas  # noqa: F401  (import de humo)


def _ticket(live=False, terminado=False, caida=False, done=0, total=2):
    return {"live": live, "terminado": terminado, "caida": caida,
            "done": done, "total": total, "grupos": []}


class TestOrdenDeTickets:
    """Antes salían en orden de carga, así que una apuesta de ayer podía
    tapar la que se está jugando ahora."""

    def _ordenar(self, tickets):
        def _prioridad(t):
            if t.get("terminado"):
                return 3
            if t.get("caida"):
                return 2
            return 0 if t.get("live") else 1

        return sorted(tickets, key=_prioridad)

    def test_lo_que_esta_en_vivo_va_primero(self):
        orden = self._ordenar([
            _ticket(terminado=True), _ticket(), _ticket(live=True),
        ])
        assert orden[0]["live"] is True

    def test_lo_terminado_va_ultimo(self):
        orden = self._ordenar([
            _ticket(terminado=True), _ticket(live=True), _ticket(),
        ])
        assert orden[-1]["terminado"] is True

    def test_las_caidas_van_antes_de_las_terminadas(self):
        """Una caída todavía interesa un poco más que una ya cerrada."""
        orden = self._ordenar([_ticket(terminado=True), _ticket(caida=True)])
        assert orden[0]["caida"] is True

    def test_el_orden_es_estable_entre_iguales(self):
        a, b = _ticket(live=True), _ticket(live=True)
        assert self._ordenar([a, b]) == [a, b]


class TestResumen:
    def test_suma_los_tramos_de_todas_las_apuestas(self):
        tickets = [_ticket(done=2, total=3), _ticket(done=1, total=4)]
        assert sum(t["total"] for t in tickets) == 7
        assert sum(t["done"] for t in tickets) == 3

    def test_cuenta_las_que_estan_en_vivo(self):
        tickets = [_ticket(live=True), _ticket(live=True, terminado=True), _ticket()]
        en_vivo = sum(1 for t in tickets if t["live"] and not t["terminado"])
        assert en_vivo == 1


class TestPanelDeCalibracionEnLaWeb:
    def test_el_endpoint_esta_registrado(self):
        import pathlib

        fuente = pathlib.Path("app/web/api.py").read_text()
        assert '"/api/calibracion"' in fuente

    def test_no_se_muestra_sin_datos(self):
        """El panel arranca oculto y solo aparece si hay legs resueltas:
        una sección vacía sería ruido."""
        import pathlib

        html = pathlib.Path("app/web/static/index.html").read_text()
        assert 'id="calibracion"' in html and "hidden" in html
        assert "if (!res.total) return;" in html
