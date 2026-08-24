"""Configuración común de los tests.

Lo importante acá: la RED ESTÁ BLOQUEADA durante los tests.

Motivo: dos tests pasaban en un entorno sin internet y fallaban en
Termux, que sí tiene. Salían a la MLB API de verdad sin que nadie lo
notara — el resultado dependía de si había conexión, de la latencia y
del estado real del calendario de ese día. Un test que consulta la red
no prueba el código: prueba internet.

Si un test necesita datos externos, tiene que mockearlos. Si se te
escapa uno, este bloqueo lo delata con la dirección que intentó abrir.
"""
import socket

import pytest


@pytest.fixture(autouse=True)
def _sin_red(monkeypatch):
    def _bloqueado(self, direccion):
        raise AssertionError(
            f"Este test intentó salir a la red ({direccion}). "
            "Mockeá la llamada: si depende de internet, no es un test."
        )

    monkeypatch.setattr(socket.socket, "connect", _bloqueado)
