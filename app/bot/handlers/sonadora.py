"""Handler de /sonadora: combinadas largas de cuota alta.

Es explícito con el usuario sobre la naturaleza del producto: una
soñadora tiene probabilidad baja por definición. Lo que la hace
defendible no es la chance de acertar, sino que cada leg tenga valor
esperado positivo — así el edge se acumula en vez de diluirse.
"""
from telegram import Update
from telegram.ext import ContextTypes

from app.analysis.combos import ValueCombo, find_dream_combos
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


def _format_dream(index: int, combo: ValueCombo) -> str:
    lineas = [f"*Soñadora {index}* · {combo.size} legs · paga *{combo.combined_odds}x*"]
    for leg in combo.legs:
        lineas.append(_format_leg(leg))
    lineas.append(
        f"   🎲 Probabilidad: *{combo.combined_probability_pct}%*  ·  "
        f"📈 Valor: *+{combo.expected_value_pct}%*"
    )
    if combo.same_game:
        lineas.append("   ⚠️ _Mismo partido: legs correlacionadas._")
    return "\n\n".join(lineas)


async def sonadora(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    processing = await update.message.reply_text("🌙 Armando soñadoras...")

    try:
        combos = find_dream_combos()
    except Exception:
        log.exception("Error armando soñadoras")
        await processing.edit_text("⚠️ Hubo un error consultando las cuotas. Probá de nuevo.")
        return

    if not combos:
        await processing.edit_text(
            "🌙 No pude armar una soñadora ahora mismo.\n\n"
            "Necesito al menos 4 props donde la probabilidad real supere a la de "
            "la cuota. Juntar legs sin valor solo para llegar a una cuota alta sería "
            "regalarte plata con una presentación linda.\n\n"
            "_Probá más cerca del horario de los partidos._",
            parse_mode="Markdown",
        )
        return

    # Guardamos para poder revisarlas después con /combos, aunque no
    # se jueguen: sirve para evaluar si las sugerencias servían.
    for c in combos:
        try:
            guardar_combo_sugerido(
                update.effective_chat.id,
                "sonadora",
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

    bloques = [
        "🌙 *Soñadoras*",
        "_Cuota alta, probabilidad baja — así funciona. Lo que las hace "
        "defendibles es que cada leg tiene valor propio, así el edge se "
        "acumula en vez de diluirse._",
        _DIVIDER,
    ]

    for i, combo in enumerate(combos, 1):
        bloques.append(_format_dream(i, combo))

    mejor = combos[0]
    bloques.append(
        _DIVIDER
        + f"\n⚠️ *Realidad*: la mejor tiene {mejor.combined_probability_pct}% de darse. "
        f"De cada 10 intentos, esperá acertar {round(mejor.combined_probability_pct / 10)} "
        "aproximadamente.\n\n"
        "_Apostá solo lo que estés dispuesto a perder._"
    )

    await edit_then_send_rest(processing, "\n\n".join(bloques))
