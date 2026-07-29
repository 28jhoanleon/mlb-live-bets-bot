"""Estados de partido de la MLB Stats API, en un solo lugar.

Antes vivían duplicados: app/mlb/live.py tenía su propia lista (para
decidir qué partidos buscar por game_pk) y app/web/service.py otra
distinta (para decidir si vale la pena pedir datos en vivo). Las dos
se desincronizaron: a la de live.py le faltaban los estados de
partido TERMINADO. Resultado: service.py creía que un partido Final
tenía datos disponibles, pero la búsqueda del game_pk por debajo lo
descartaba siempre por no estar "en curso" — la leg caía al promedio
histórico aunque el partido ya hubiera terminado.
"""
from __future__ import annotations

EN_CURSO = ("In Progress", "Manager challenge", "Warmup", "Delayed")
TERMINADO = ("Final", "Game Over", "Completed Early")
CON_DATOS = EN_CURSO + TERMINADO
