#!/bin/bash
# Sube el proyecto a GitHub, revisando antes que no se filtren secretos.
#
# Uso:  bash subir.sh
#
# Lo único que no automatiza es el token de GitHub: te lo va a pedir el
# propio git cuando haga falta. Eso es a propósito — tu credencial no
# tiene que quedar escrita en ningún archivo.

set -e
cd ~/mlb-live-bets-bot

echo "=== 1. Revisando que no se filtren secretos ==="

if [ ! -f .gitignore ] || ! grep -q "^\.env$" .gitignore; then
  echo "FRENO: .gitignore no está protegiendo el archivo .env"
  echo "Sin eso tus claves irían públicas a GitHub."
  exit 1
fi

if git ls-files --error-unmatch .env >/dev/null 2>&1; then
  echo "FRENO: el archivo .env está siendo rastreado por git."
  echo "Sacalo con:  git rm --cached .env"
  exit 1
fi

# Buscamos claves pegadas por error dentro del código
if git grep -lIE "sk-proj-[A-Za-z0-9_-]{20}|[0-9]{9,10}:AA[A-Za-z0-9_-]{30}" -- . ':!*.md' 2>/dev/null | grep -q .; then
  echo "FRENO: parece haber una clave escrita dentro del código:"
  git grep -lIE "sk-proj-[A-Za-z0-9_-]{20}|[0-9]{9,10}:AA[A-Za-z0-9_-]{30}" -- . ':!*.md'
  echo "Sacala de ahí y dejala solo en .env"
  exit 1
fi

echo "OK: no hay secretos a la vista"
echo

echo "=== 2. Corriendo los tests ==="
# Ojo: hay que guardar el resultado ANTES de pasarlo por una tubería.
# Con `pytest | tail`, bash lee el resultado de tail (siempre 0) y
# reporta verde aunque los tests fallen.
salida=$(python -m pytest tests/ -q 2>&1) && estado=0 || estado=$?
echo "$salida" | tail -4

if [ $estado -eq 0 ]; then
  echo "OK: tests en verde"
else
  echo
  echo "HAY TESTS FALLANDO. Subir así puede romper el deploy."
  read -p "¿Seguir igual? (s/N) " r
  [ "$r" = "s" ] || exit 1
fi
echo

echo "=== 3. Limpiando lo que no va al repo ==="
# Caches y respaldos de editor: ensucian el historial y no aportan nada
rm -rf .pytest_cache
find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
find . -name "*.save" -delete 2>/dev/null || true
echo "OK"
echo

echo "=== 4. Qué se va a subir ==="
git add -A
git status --short
echo

read -p "¿Confirmás? (s/N) " ok
[ "$ok" = "s" ] || { echo "Cancelado."; exit 0; }

git commit -m "Bot + web con seguimiento de apuestas en vivo" || echo "(sin cambios nuevos)"

echo
echo "=== 5. Subiendo ==="
echo "Si pide contraseña: NO es la de tu cuenta, es un token."
echo "Se genera en GitHub → Settings → Developer settings →"
echo "Personal access tokens → Tokens (classic) → marcar 'repo'"
echo

git push

echo
echo "Listo. El código ya está en GitHub."
echo "Ahora seguí desde el paso 2 de DEPLOY.md (crear el proyecto en Railway)."
