#!/bin/bash
# Deja tu carpeta con SOLO la versión nueva, sin restos de versiones viejas.
#
# El problema: `cp -r` copia y sobrescribe, pero nunca borra. Después de
# muchas versiones quedaron módulos duplicados (sonadora.py y
# sonadoras.py, app/db/ y app/database/) y archivos .save. Dos módulos
# con nombres parecidos son peligrosos: Python puede importar el viejo.
#
# Qué conserva: tu .env, la base de datos y el historial de git.
# Qué reemplaza: todo el código.
#
# Uso:  bash limpiar_e_instalar.sh /ruta/a/la/version/nueva

set -e

ORIGEN="${1:-$HOME/storage/downloads/mlb-live-bets-bot-v30/mlb-live-bets-bot}"
DESTINO="$HOME/mlb-live-bets-bot"

echo "Origen : $ORIGEN"
echo "Destino: $DESTINO"
echo

if [ ! -f "$ORIGEN/main.py" ]; then
  echo "FRENO: no encuentro main.py en el origen."
  echo "Revisá la ruta. Para ver qué descomprimiste:"
  echo "  ls ~/storage/downloads/ | grep mlb"
  exit 1
fi

if [ ! -d "$ORIGEN/app/web" ]; then
  echo "FRENO: el origen no tiene app/web, así que no es la versión nueva."
  exit 1
fi

cd "$DESTINO"

echo "=== 1. Guardando lo que no se toca ==="
RESPALDO=$(mktemp -d)
[ -f .env ] && cp .env "$RESPALDO/" && echo "  .env guardado"
for db in *.db; do
  [ -f "$db" ] && cp "$db" "$RESPALDO/" && echo "  $db guardado"
done
echo

echo "=== 2. Borrando el código viejo ==="
# Solo el código. .git, .env y las bases quedan intactos.
rm -rf app tests
rm -f main.py requirements.txt Procfile railway.json DEPLOY.md subir.sh
rm -rf .pytest_cache
find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
find . -name "*.save" -delete 2>/dev/null || true
echo "  listo"
echo

echo "=== 3. Copiando la versión nueva ==="
cp -r "$ORIGEN"/. "$DESTINO"/
echo "  listo"
echo

echo "=== 4. Restaurando lo tuyo ==="
[ -f "$RESPALDO/.env" ] && cp "$RESPALDO/.env" . && echo "  .env restaurado"
for db in "$RESPALDO"/*.db; do
  [ -f "$db" ] && cp "$db" . && echo "  $(basename "$db") restaurado"
done
rm -rf "$RESPALDO"
echo

echo "=== 5. Comprobando ==="
FALLA=0
[ -d app/web ] && echo "  OK  app/web existe" || { echo "  FALTA app/web"; FALLA=1; }
[ -f app/web/static/index.html ] && echo "  OK  la web está" || { echo "  FALTA la web"; FALLA=1; }
[ -f .env ] && echo "  OK  .env conservado" || echo "  AVISO: no había .env"
[ -f app/bot/handlers/sonadoras.py ] && { echo "  QUEDÓ un duplicado viejo"; FALLA=1; } || echo "  OK  sin duplicados"
[ -d app/database ] && { echo "  QUEDÓ app/database duplicado"; FALLA=1; } || echo "  OK  sin app/database"
echo

if [ $FALLA -ne 0 ]; then
  echo "Algo no quedó bien. No sigas: contame qué dice."
  exit 1
fi

echo "=== 6. Instalando dependencias ==="
# No abortamos si falla: puede ser un entorno que exija --break-system-packages.
# Mejor avisar y seguir que cortar todo con el código ya instalado.
# No escondemos la salida de pip: la vez pasada ocultó que el problema
# real era una dependencia que no compila en Android.
if pip install -r requirements.txt 2>&1 | tail -5; then
  echo "  listo"
else
  echo "  AVISO: revisá el mensaje de arriba."
fi
echo

echo "=== 7. Tests ==="
salida=$(python -m pytest tests/ -q 2>&1) && estado=0 || estado=$?
echo "$salida" | tail -4

if [ $estado -eq 0 ]; then
  echo
  echo "Todo en orden. Ahora podés correr:  bash subir.sh"
else
  echo
  echo "Hay tests fallando. Pasame la salida antes de subir nada."
fi
