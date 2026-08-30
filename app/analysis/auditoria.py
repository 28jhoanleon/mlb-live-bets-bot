"""Audita las apuestas que armó el usuario: qué tramos la sostienen, qué
tramos la están hundiendo, y con qué se podrían reemplazar.

La idea es la que ya venía haciendo a mano: armar una combinada, mirar
los números que devuelve el bot, y rehacerla mejor. Esto lo automatiza.

Una aclaración honesta sobre el alcance: la comparación es entre lo que
el jugador viene haciendo (últimos partidos reales) y lo que implica la
cuota. No sabe de lesiones, de quién lanza enfrente, ni del clima. Es una
segunda opinión con números, no un oráculo.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.analysis.probability import (
    ProbabilityError,
    estimate_leg_probability,
    precalentar_cache,
)
from app.utils.logger import get_logger

log = get_logger(__name__)

# Por debajo de esto la leg está tirando la combinada para abajo.
PROB_FLOJA = 45.0
# Por encima de esto la leg es un ancla: la parte que sostiene el ticket.
PROB_FUERTE = 70.0


@dataclass
class LegAuditada:
    player: str
    market: str
    line: str
    probabilidad: float | None      # None = no se pudo estimar
    promedio: float | None
    muestra: int
    sugerencia: str | None = None   # otra línea del mismo mercado
    error: str | None = None

    @property
    def es_floja(self) -> bool:
        return self.probabilidad is not None and self.probabilidad < PROB_FLOJA

    @property
    def es_fuerte(self) -> bool:
        return self.probabilidad is not None and self.probabilidad >= PROB_FUERTE


@dataclass
class AuditoriaTicket:
    legs: list[LegAuditada] = field(default_factory=list)
    probabilidad_combinada: float | None = None

    @property
    def flojas(self) -> list[LegAuditada]:
        return [l for l in self.legs if l.es_floja]

    @property
    def fuertes(self) -> list[LegAuditada]:
        return [l for l in self.legs if l.es_fuerte]

    @property
    def sin_datos(self) -> list[LegAuditada]:
        return [l for l in self.legs if l.probabilidad is None]


def auditar_legs(legs_raw: list[dict]) -> AuditoriaTicket:
    """Estima cada leg del ticket y las clasifica."""
    auditadas: list[LegAuditada] = []

    # Traer todos los jugadores del ticket de una, en paralelo: con 12
    # tramos, hacerlo de a uno son 24 llamadas encadenadas.
    precalentar_cache([l.get("player") for l in legs_raw if l.get("player")])

    for leg in legs_raw:
        jugador = leg.get("player") or "?"
        mercado = leg.get("market") or ""
        linea = leg.get("line") or ""

        if not leg.get("player"):
            # Mercados de equipo/partido: no se estiman con historial de
            # jugador. Se listan igual para no ocultarle nada al usuario.
            auditadas.append(LegAuditada(
                player="Apuesta de equipo", market=mercado, line=linea,
                probabilidad=None, promedio=None, muestra=0,
                error="mercado de equipo, no lo estimo",
            ))
            continue

        try:
            est = estimate_leg_probability(jugador, mercado, linea)
        except ProbabilityError as e:
            auditadas.append(LegAuditada(
                player=jugador, market=mercado, line=linea,
                probabilidad=None, promedio=None, muestra=0, error=str(e),
            ))
            continue
        except Exception:
            log.exception("Error auditando leg")
            auditadas.append(LegAuditada(
                player=jugador, market=mercado, line=linea,
                probabilidad=None, promedio=None, muestra=0,
                error="no pude traer los datos",
            ))
            continue

        auditadas.append(LegAuditada(
            player=est.player, market=mercado, line=linea,
            probabilidad=est.probability_pct, promedio=est.avg_value,
            muestra=est.sample_size, sugerencia=est.sugerencia,
        ))

    # Probabilidad de que entren TODAS. Se multiplican como si fueran
    # independientes, que no lo son del todo (dos bateadores del mismo
    # equipo se ayudan entre sí), pero sirve de referencia.
    estimadas = [l.probabilidad for l in auditadas if l.probabilidad is not None]
    combinada = None
    if estimadas and len(estimadas) == len(auditadas):
        prob = 1.0
        for p in estimadas:
            prob *= p / 100
        combinada = round(prob * 100, 1)

    return AuditoriaTicket(legs=auditadas, probabilidad_combinada=combinada)


def proponer_reemplazos(
    auditoria: AuditoriaTicket, picks: list, max_por_leg: int = 2
) -> list[tuple[LegAuditada, list]]:
    """Para cada leg floja, busca picks del día que la superen.

    Devuelve [(leg_floja, [picks candidatos])]. Excluye jugadores que ya
    están en el ticket: repetir un jugador en la misma combinada
    concentra el riesgo en vez de repartirlo.
    """
    ya_usados = {l.player.lower() for l in auditoria.legs if l.player}

    propuestas = []
    for floja in auditoria.flojas:
        candidatos = [
            p for p in picks
            if p.player.lower() not in ya_usados
            and p.our_probability_pct > (floja.probabilidad or 0) + 10
        ]
        candidatos.sort(key=lambda p: p.our_probability_pct, reverse=True)
        if candidatos:
            propuestas.append((floja, candidatos[:max_por_leg]))
    return propuestas


def armar_mejorada(auditoria: AuditoriaTicket, picks: list) -> list:
    """Arma la versión mejorada: conserva los tramos que ya son buenos y
    reemplaza los flojos por los mejores picks disponibles.

    Devuelve una lista mezclada de LegAuditada (las que se conservan) y
    DailyPick (las nuevas), en el orden en que iría el ticket.
    """
    ya_usados = {l.player.lower() for l in auditoria.legs if l.player}
    disponibles = sorted(
        [p for p in picks if p.player.lower() not in ya_usados],
        key=lambda p: p.our_probability_pct,
        reverse=True,
    )

    mejorada = []
    for leg in auditoria.legs:
        if leg.es_floja or leg.probabilidad is None:
            # Buscar un reemplazo claramente mejor; si no hay, se avisa
            # que esa parte queda sin cubrir en vez de meter cualquier cosa.
            reemplazo = next(
                (p for p in disponibles
                 if p.our_probability_pct > (leg.probabilidad or 0) + 10),
                None,
            )
            if reemplazo:
                disponibles.remove(reemplazo)
                ya_usados.add(reemplazo.player.lower())
                mejorada.append(reemplazo)
                continue
        mejorada.append(leg)
    return mejorada


# --- Versión segura -----------------------------------------------------
#
# Distinto de las soñadoras: acá no se busca cuota alta, se busca que la
# combinada ENTRE. Se conservan los mismos jugadores y mercados que
# eligió el usuario y se BAJAN las líneas hasta que cada tramo alcance el
# objetivo. Pierde cuota, gana probabilidad.

# Umbral por tramo. Elegido con la cuenta a la vista:
#
#   tramos |   80%  |   85%  |   90%
#        4 | 37.4%  | 47.6%  | 59.9%   <- que entren TODAS
#   paga   | 2.44x  | 1.92x  | 1.52x
#
# Con 80% una combinada de 4 no llega ni a la mitad de las veces, así que
# llamarla "segura" sería mentir. Con 90% entra más seguido pero paga tan
# poco que no compensa el riesgo. 85% es el punto donde las dos cosas
# siguen teniendo sentido.
OBJETIVO_SEGURO = 85.0

# Debajo de esto un porcentaje de calibración es ruido, no señal: con
# pocas legs, "acertó 10 de 15" no distingue un modelo de 85% de uno de
# 70%. Mismo piso que usa /calibracion, a propósito -- es la misma
# pregunta ("¿esta muestra ya significa algo?") aplicada dos veces.
_MUESTRA_MINIMA_PARA_AJUSTAR = 20


def _prob_calibrada(prob_cruda: float, chat_id: int | None) -> float:
    """Corrige la probabilidad de UNA línea contra lo que en verdad pasó
    en ese rango, si ya hay muestra.

    Ojo con la versión anterior de esto: bajaba la META (85% -> el real
    del rango, por ejemplo 65%) en vez de corregir la ESTIMACIÓN. Con
    esa versión, un modelo sobreconfiado hacía que /mejorar aceptara
    MÁS líneas débiles, no menos -- el efecto contrario al buscado. Acá
    se hace al revés: la meta queda fija en OBJETIVO_SEGURO, y lo que
    se ajusta es cuánto confiar en la estimación cruda antes de
    compararla contra esa meta. Si el modelo viene sobrevendiendo en
    ese rango, esto la baja, y entonces hacen falta líneas MÁS flojas
    (más seguras) para que una entre -- que es lo que "seguro" debería
    significar.
    """
    if chat_id is None:
        return prob_cruda

    from app.db.database import calibracion

    piso = min(int(prob_cruda // 10 * 10), 90)
    for tramo in calibracion(chat_id):
        if tramo["tramo"] == f"{piso}-{piso + 9}%" and tramo["muestra"] >= _MUESTRA_MINIMA_PARA_AJUSTAR:
            return tramo["real_pct"]
    return prob_cruda


@dataclass
class LegSegura:
    player: str
    match: str
    market: str
    linea_original: str
    linea_nueva: str
    probabilidad: float
    cambio: bool
    # True cuando NINGUNA línea del mercado llega al objetivo. Se marca
    # en vez de descartarse en silencio: saber cuál es el tramo que no
    # da es justamente la información útil.
    no_alcanza: bool = False


def version_segura(
    legs_raw: list[dict], objetivo: float = OBJETIVO_SEGURO, chat_id: int | None = None,
) -> tuple[list[LegSegura], float | None]:
    """Baja las líneas de cada tramo hasta alcanzar el objetivo.

    La meta (`objetivo`) queda siempre fija: lo que se corrige, si hay
    calibración con muestra suficiente, es la CONFIANZA en cada
    estimación antes de compararla contra esa meta -- no la meta en sí.
    Ver `_prob_calibrada` para el porqué.

    Devuelve (tramos, probabilidad combinada). La probabilidad combinada
    se calcula multiplicando, con la misma penalización por dependencia
    que usa el resto del proyecto: cuatro tramos al 90% no dan 90%, dan
    ~65%. Decirlo claro evita vender una seguridad que no existe.
    """
    from app.analysis.probability import sugerir_lineas

    salidas: list[LegSegura] = []
    for leg in legs_raw:
        jugador = leg.get("player")
        mercado = leg.get("market") or ""
        linea = leg.get("line") or ""
        if not jugador:
            continue

        try:
            opciones = sugerir_lineas(jugador, mercado, linea)
        except Exception:
            log.debug("Sin alternativas para %s", jugador, exc_info=True)
            continue
        if not opciones:
            continue

        actual = next((o for o in opciones if o.es_la_apostada), None)
        lado = actual.side if actual else "Over"

        # Del mismo lado, la línea MÁS exigente que igual llegue al
        # objetivo -- comparando la probabilidad CALIBRADA, no la
        # cruda. Así se baja el riesgo sin regalar cuota de más.
        candidatas = [
            o for o in opciones
            if o.side == lado and _prob_calibrada(o.probabilidad_pct, chat_id) >= objetivo
        ]
        if not candidatas:
            # Ni la línea más floja llega al objetivo: se informa la
            # mejor disponible en vez de omitir el tramo en silencio.
            candidatas = [max(opciones, key=lambda o: _prob_calibrada(o.probabilidad_pct, chat_id))]

        elegida = (
            max(candidatas, key=lambda o: o.linea) if lado == "Over"
            else min(candidatas, key=lambda o: o.linea)
        )
        prob_mostrada = round(_prob_calibrada(elegida.probabilidad_pct, chat_id), 1)

        salidas.append(LegSegura(
            player=jugador,
            match=leg.get("match") or "",
            market=mercado,
            linea_original=linea,
            linea_nueva=f"{elegida.side} {elegida.linea:g}",
            probabilidad=prob_mostrada,
            cambio=(actual is None or elegida.linea != actual.linea),
            no_alcanza=prob_mostrada < objetivo,
        ))

    if not salidas:
        return [], None

    # La probabilidad se calcula SOLO con los tramos que alcanzan el
    # objetivo: es la apuesta que de verdad se recomienda. Incluir los
    # que no dan mostraría un número peor que el de la apuesta sugerida.
    buenos = [s for s in salidas if not s.no_alcanza]
    if not buenos:
        return salidas, None

    prob = 1.0
    for s in buenos:
        prob *= s.probabilidad / 100
    # Misma penalización por dependencia que en combos.py: los tramos
    # comparten día y condiciones, no son independientes.
    prob *= 0.97 ** max(0, len(buenos) - 1)

    return salidas, round(prob * 100, 1)
