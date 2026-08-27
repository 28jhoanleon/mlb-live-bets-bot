"""/fuentes — qué grupos seguir y con qué filtros.

Cada fuente es un grupo de Telegram con sus propias condiciones. De uno
puede interesarte todo; de otro, solo lo que publica cierta persona, o
solo los mensajes con foto o con link. Sin filtros, seguir varios
grupos convierte la pestaña en un chat entero y deja de servir.
"""
from __future__ import annotations

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from app.db.database import agregar_fuente, borrar_fuente, listar_fuentes
from app.utils.logger import get_logger
from app.utils.telegram_helpers import escape_md

log = get_logger(__name__)

_AYUDA = """*Fuentes de picks*

`/fuentes` — ver las configuradas
`/fuentes add <grupo> <nombre>` — seguir un grupo
`/fuentes del <grupo>` — dejar de seguirlo

*Filtros* (opcionales, después del nombre):
`autor:Ludo` — solo lo que publica esa persona
`foto` — solo mensajes con imagen
`link` — solo mensajes con un enlace
`con:mlb,over` — solo si aparece alguna de esas palabras

*Ejemplos:*
`/fuentes add ludogallina2024 Ludo MLB con:mlb`
`/fuentes add otrogrupo Picks autor:Juan foto`
"""


def _describir(f: dict) -> str:
    partes = []
    if f.get("autores"):
        partes.append(f"autor: {f['autores']}")
    if f.get("requiere_foto"):
        partes.append("con foto")
    if f.get("requiere_link"):
        partes.append("con link")
    if f.get("palabras"):
        partes.append(f"palabras: {f['palabras']}")
    filtros = " · ".join(partes) or "sin filtros"
    return f"*{escape_md(f['nombre'])}* (@{escape_md(f['grupo'])})\n   _{escape_md(filtros)}_"


async def fuentes_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []

    if not args:
        actuales = listar_fuentes()
        if not actuales:
            await update.message.reply_text(
                "No estás siguiendo ningún grupo todavía.\n\n" + _AYUDA,
                parse_mode=ParseMode.MARKDOWN,
            )
            return
        lineas = ["*Grupos que seguís:*", ""]
        lineas += [_describir(f) for f in actuales]
        lineas.append("")
        lineas.append("`/fuentes add ...` para agregar · `/fuentes del <grupo>` para sacar")
        await update.message.reply_text("\n".join(lineas), parse_mode=ParseMode.MARKDOWN)
        return

    accion = args[0].lower()

    if accion in ("del", "borrar", "quitar") and len(args) > 1:
        if borrar_fuente(args[1]):
            await update.message.reply_text(f"Dejé de seguir {args[1]}.")
        else:
            await update.message.reply_text(f"No estaba siguiendo {args[1]}.")
        return

    if accion not in ("add", "agregar"):
        await update.message.reply_text(_AYUDA, parse_mode=ParseMode.MARKDOWN)
        return

    if len(args) < 2:
        await update.message.reply_text(
            "Falta el grupo. Ej: `/fuentes add ludogallina2024 Ludo MLB`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    grupo = args[1]
    autores, palabras = "", ""
    foto = link = False
    nombre_partes = []

    for token in args[2:]:
        bajo = token.lower()
        if bajo.startswith("autor:"):
            autores = token.split(":", 1)[1]
        elif bajo.startswith("con:"):
            palabras = token.split(":", 1)[1]
        elif bajo == "foto":
            foto = True
        elif bajo == "link":
            link = True
        else:
            nombre_partes.append(token)

    nombre = " ".join(nombre_partes) or grupo

    try:
        agregar_fuente(nombre, grupo, autores, foto, link, palabras)
    except Exception:
        log.exception("No pude guardar la fuente")
        await update.message.reply_text("No pude guardarla. Está en los logs.")
        return

    guardada = next((f for f in listar_fuentes() if f["grupo"] == grupo.lstrip("@")), None)
    await update.message.reply_text(
        "Listo, ahora sigo:\n\n" + (_describir(guardada) if guardada else nombre),
        parse_mode=ParseMode.MARKDOWN,
    )
