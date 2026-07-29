"""Handler de /value: arma COMBINADAS con valor esperado positivo.

Cambio de enfoque respecto a la versión anterior (que listaba apuestas
sueltas): ahora se buscan legs con valor real y se combinan.

Regla que no se negocia: solo entran al combo legs que YA tienen valor
por separado. Una leg mala arrastra a todo el combo por más que las
otras sean buenas, así que no se rellena para llegar a una cuota linda.
"""
from telegram import Update
from telegram.ext import ContextTypes

from app.analysis.combos import ValueCombo, find_value_combos
from app.db.database import guardar_combo_sugerido
from app.utils.logger import get_logger
from app.utils.market_labels import nombre_stake
from app.utils.equipos import partido_corto
from app.utils.tiempo import formato_hora_fecha
from app.utils.telegram_helpers import edit_then_send_rest, escape_md

log = get_logger(__name__)

_DIVIDER = "━━━━━━━━━━━━━━━━"


def _format_leg(leg) -> str:
    """Una leg con todo lo necesario para encontrarla en la app:
    equipo, jugador, el nombre EXACTO del mercado en Stake, y el horario
    del partido en hora argentina."""
    # Abreviatura (NYY @ BOS): identifica el partido de un vistazo
    # sin ocupar toda la línea con nombres largos.
    partido = escape_md(partido_corto(leg.match))
    hora = formato_hora_fecha(leg.commence_time)
    return (
        f"   {escape_md(leg.player)} · {leg.probability_pct}%\n"
        f"   _{escape_md(nombre_stake(leg.market))}_ {escape_md(leg.line)} @ {leg.odds}\n"
        f"   {partido} · 🕐 {hora}"
    )


def _format_combo(index: int, combo: ValueCombo) -> str:
    lineas = [f"*Combinada {index}* · {combo.size} legs · cuota *{combo.combined_odds}*"]
    for leg in combo.legs:
        lineas.append(_format_leg(leg))
    lineas.append(
        f"   ✅ Probabilidad: *{combo.combined_probability_pct}%*  ·  "
        f"📈 Valor: *+{combo.expected_value_pct}%*"
    )
    if combo.same_game:
        lineas.append("   ⚠️ _Mismo partido: legs correlacionadas._")
    return "\n\n".join([lineas[0]] + lineas[1:])


async def value(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    processing = await update.message.reply_text("🔍 Buscando combinadas con valor...")

    try:
        combos = find_value_combos()
    except Exception:
        log.exception("Error armando combinadas con valor")
        await processing.edit_text("⚠️ Hubo un error consultando las cuotas. Probá de nuevo.")
        return

    if not combos:
        await processing.edit_text(
            "🔍 No encontré combinadas con valor ahora mismo.\n\n"
            "Para armar una necesito al menos 2 props donde la probabilidad real "
            "del jugador supere a la que implica la cuota. Si el mercado está bien "
            "ajustado, forzar un combo sería venderte humo.\n\n"
            "_Probá más cerca del horario de los partidos, cuando se cargan más props._",
            parse_mode="Markdown",
        )
        return

    # Guardamos para poder revisarlas después con /combos, aunque no
    # se jueguen: sirve para evaluar si las sugerencias servían.
    for c in combos:
        try:
            guardar_combo_sugerido(
                update.effective_chat.id,
                "value",
                [
                    {
                        "player": l.player,
                        "market": l.market,
                        "line": l.line,
                        "match": l.match,
                        "odds": l.odds,
                    }
                    for l in c.legs
                ],
                c.combined_odds,
                c.combined_probability_pct,
            )
        except Exception:
            log.exception("No pude guardar el combo sugerido")

    bloques = ["🎯 *Combinadas con valor*", _DIVIDER]
    for i, combo in enumerate(combos, 1):
        bloques.append(_format_combo(i, combo))

    bloques.append(
        _DIVIDER
        + "\n_Solo se combinan legs que ya tienen valor por separado. "
        "La probabilidad sale de los últimos partidos reales de cada jugador, "
        "no de la cuota._"
    )

    await edit_then_send_rest(processing, "\n\n".join(bloques))
