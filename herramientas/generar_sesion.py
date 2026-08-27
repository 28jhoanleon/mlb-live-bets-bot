"""Genera el valor de TELEGRAM_SESSION. Se corre UNA sola vez.

Uso, desde Termux o tu computadora:

    pip install telethon
    python herramientas/generar_sesion.py

Te va a pedir:
  - API ID y API HASH, que sacás de https://my.telegram.org
    (Iniciás sesión con tu número → API development tools → creás una app)
  - Tu número de teléfono con código de país, ej. +5491112345678
  - El código que te llega por Telegram
  - Tu contraseña, si tenés verificación en dos pasos

Al final imprime una cadena larga. ESA cadena es la sesión: cargala en
Railway como TELEGRAM_SESSION.

IMPORTANTE
----------
Esa cadena da acceso a TODO tu Telegram. Tratala como una contraseña:
no la pegues en un chat, no la subas al repositorio, no se la mandes a
nadie. Si alguna vez se te escapa, andá a Telegram → Ajustes →
Dispositivos y cerrá esa sesión: queda invalidada al instante.
"""
import sys

try:
    from telethon import TelegramClient
    from telethon.sessions import StringSession
except ImportError:
    sys.exit("Falta Telethon. Instalalo con:  pip install telethon")


def main() -> None:
    print("Sacá tus credenciales de https://my.telegram.org")
    print("(Iniciá sesión → API development tools → creá una app)\n")

    api_id = input("API ID: ").strip()
    api_hash = input("API HASH: ").strip()

    if not api_id.isdigit():
        sys.exit("El API ID tiene que ser un número.")

    with TelegramClient(StringSession(), int(api_id), api_hash) as cliente:
        # Nada de get_me() acá: dentro del `with` de Telethon devuelve
        # una corrutina sin resolver y rompía el script JUSTO DESPUÉS de
        # iniciar sesión, o sea en el peor momento: la sesión quedaba
        # creada pero nunca se imprimía. Era solo cosmético.
        sesion = cliente.session.save()

        print("\nListo, sesión iniciada.")
        print("\nCargá esto en Railway (Variables):\n")
        print(f"  TELEGRAM_API_ID    = {api_id}")
        print(f"  TELEGRAM_API_HASH  = {api_hash}")
        print(f"  TELEGRAM_GRUPO     = ludogallina2024")
        print(f"  TELEGRAM_SESSION   = {sesion}")
        print("\nNo compartas la última: da acceso a todo tu Telegram.")
        print("Si se te escapa, cerrá la sesión desde Telegram → Ajustes → Dispositivos.")


if __name__ == "__main__":
    main()
