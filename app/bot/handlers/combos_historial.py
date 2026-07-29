"""Handler de /combos: historial de combinadas sugeridas por el bot.

Muestra las que sugirió /value y /sonadora, y resuelve automáticamente
las que ya se pueden verificar contra los resultados reales de la MLB.

La gracia es poder mirar en retrospectiva si las sugerencias servían,
independientemente de que las hayas jugado o no.
"""
from telegram import Update
from telegram.ext import ContextTypes

from app.analysis.probability import (
    ProbabilityError,
    _classify_batter_market,
    _classify_pitcher_market,
    _parse_line,
)
from app.db.database import listar_combos_sugeridos, marcar_resultado_combo
from app.mlb.players import get_recent_hitting_games, search_player
from app.utils.logger import get_logger
from app.utils.market_labels import nombre_stake
from app.utils.telegram_helpers import edit_then_send_rest, escape_md
from app.utils.tiempo import a_local

log = get_logger(__name__)

_DIVIDER = "━━━━━━━━━━━━━━━━"


def _resolver_leg(leg: dict) -> bool | None:
    """¿Se cumplió esta leg? None si todavía no se puede saber.

    Busca el partido del jugador en la fecha en que se sugirió y compara
    con la línea. Si no encuentra datos, devuelve None en vez de asumir
    que perdió: dar por perdida una leg sin verificarla sería peor que
    no responder.
    """
    player_name = leg.get("player")
    if not player_name:
        return None

    try:
        side, threshold = _parse_line(leg.get("line", ""))
    except ProbabilityError:
        return None

    player = search_player(player_name)
    if not player or not player.get("id"):
        return None

    es_pitcher = player.get("position") == "Pitcher"
    try:
        campos = (
            _classify_pitcher_market(leg.get("market", ""))
            if es_pitcher
            else _classify_batter_market(leg.get("market", ""))
        )
    except ProbabilityError:
        return None

    try:
        partidos = get_recent_hitting_games(player["id"], last_n=5)
    except Exception:
        log.exception("Error trayendo partidos para resolver leg")
        return None

    if not partidos:
        return None

    # Usamos el partido más reciente: es el que corresponde a la sugerencia
    valor = sum(partidos[0].get(c, 0) for c in campos)
    return valor > threshold if side == "Over" else valor < threshold


def _resolver_combo(combo: dict) -> str | None:
    """'ganada', 'perdida', o None si falta información."""
    resultados = [_resolver_leg(leg) for leg in combo.get("legs", [])]
    if any(r is None for r in resultados):
        return None
    return "ganada" if all(resultados) else "perdida"


def _formatear(combo: dict) -> str:
    fecha = a_local(combo.get("creado_en"))
    fecha_txt = fecha.strftime("%d/%m %H:%M") if fecha else "?"

    icono = {"ganada": "✅", "perdida": "❌"}.get(combo.get("resultado"), "⏳")
    tipo = "🌙 Soñadora" if combo["tipo"] == "sonadora" else "🎯 Combinada"

    lineas = [
        f"{icono} *{tipo}* · {fecha_txt}",
        f"   cuota {combo['cuota']} · probabilidad {combo['probabilidad']}%",
    ]
    for leg in combo.get("legs", []):
        lineas.append(
            f"   • {escape_md(leg.get('player', '?'))} — "
            f"{escape_md(nombre_stake(leg.get('market', '')))} {escape_md(leg.get('line', ''))}"
        )
    if combo.get("resultado") == "perdida":
        lineas.append("   _no se dio_")
    elif combo.get("resultado") == "ganada":
        lineas.append("   _se dio_ 🎉")
    else:
        lineas.append("   _todavía sin resolver_")
    return "\n".join(lineas)


async def combos(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    processing = await update.message.reply_text("📜 Buscando combinadas sugeridas...")

    try:
        guardados = listar_combos_sugeridos(chat_id, limite=10)
    except Exception:
        log.exception("Error leyendo combos sugeridos")
        await processing.edit_text("⚠️ Hubo un error leyendo el historial.")
        return

    if not guardados:
        await processing.edit_text(
            "📜 Todavía no hay combinadas guardadas.\n\n"
            "Se guardan solas cada vez que usás /value o /sonadora, "
            "así después podés ver si se daban o no."
        )
        return

    # Intentamos resolver las que siguen pendientes
    resueltas_ahora = 0
    for combo in guardados:
        if combo.get("resultado"):
            continue
        resultado = _resolver_combo(combo)
        if resultado:
            try:
                marcar_resultado_combo(combo["id"], resultado)
                combo["resultado"] = resultado
                resueltas_ahora += 1
            except Exception:
                log.exception("No pude guardar el resultado del combo %s", combo["id"])

    ganadas = sum(1 for c in guardados if c.get("resultado") == "ganada")
    resueltas = sum(1 for c in guardados if c.get("resultado"))

    encabezado = ["📜 *Combinadas sugeridas*"]
    if resueltas:
        encabezado.append(f"_{ganadas} de {resueltas} resueltas se dieron_")
    if resueltas_ahora:
        encabezado.append(f"_({resueltas_ahora} resueltas recién)_")

    bloques = ["\n".join(encabezado), _DIVIDER]
    bloques.extend(_formatear(c) for c in guardados)

    await edit_then_send_rest(processing, "\n\n".join(bloques))
