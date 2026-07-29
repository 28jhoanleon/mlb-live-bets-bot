#!/bin/bash
# Limpia archivos de versiones viejas.
#
# Por qué hace falta: al actualizar con `cp -r`, los archivos nuevos se
# copian encima pero los VIEJOS nunca se borran. Después de muchas
# versiones quedan módulos duplicados y archivos muertos que se subirían
# a GitHub y pueden confundir (dos bases de datos, dos versiones del
# mismo módulo).
#
# Es seguro: solo borra rutas concretas que ya no existen en el proyecto.
# No toca .env, ni .git, ni nada tuyo.
#
# Uso:  bash limpiar.sh

set -e
cd ~/mlb-live-bets-bot

VIEJOS=(
  "app/database"            # reemplazado por app/db
  "app/models"              # ya no se usa
  "app/ocr"                 # se usa visión multimodal, no OCR
  "app/ai/analyzer.py"      # reemplazado por app/ai/vision.py
  "app/mlb/client.py"       # shim viejo, ya nadie lo importa
  "app/utils/helpers.py"    # reemplazado por utils específicos
  "app/bot/telegram_bot.py.save"   # copia de respaldo de un editor
  ".pytest_cache"           # basura de los tests
)

echo "=== Archivos de versiones viejas ==="
encontrados=0
for ruta in "${VIEJOS[@]}"; do
  if [ -e "$ruta" ]; then
    echo "  - $ruta"
    encontrados=$((encontrados+1))
  fi
done

if [ "$encontrados" -eq 0 ]; then
  echo "  (ninguno: la carpeta ya está limpia)"
  exit 0
fi

echo
read -p "¿Borrar estos $encontrados? (s/N) " ok
[ "$ok" = "s" ] || { echo "Cancelado."; exit 0; }

for ruta in "${VIEJOS[@]}"; do
  [ -e "$ruta" ] && rm -rf "$ruta" && echo "borrado: $ruta"
done

# Si alguno ya había sido subido a git, hay que sacarlo del índice
git rm -r --cached --ignore-unmatch -q app/database app/models app/ocr .pytest_cache 2>/dev/null || true

echo
echo "Listo. Ahora verificá que todo siga funcionando:"
echo "  python -m pytest tests/ -q"
