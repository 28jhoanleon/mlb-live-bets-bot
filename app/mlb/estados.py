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

# Cuántos días hacia atrás buscar un partido con datos (en curso o
# terminado) antes de darlo por no encontrado. Con 1 solo día alcanzaba
# para el caso de partido nocturno que cruza la medianoche, pero no para
# un ticket que el usuario recién vuelve a mirar más tarde: si ya pasó
# más de un día, antes no lo encontraba NUNCA -y al no encontrarlo,
# tampoco se podía marcar terminado para que el auto-borrado lo sacara.
DIAS_HACIA_ATRAS = 3
