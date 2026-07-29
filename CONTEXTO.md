# MLB Live Bets — estado del proyecto

Pegá este archivo (o su contenido) al empezar un chat nuevo para retomar
sin explicar todo de cero.

---

## Qué es

Bot de Telegram + web para seguir apuestas de MLB. Lee capturas de la
casa de apuestas con visión por IA, cruza los jugadores contra la MLB
Stats API y muestra el avance de cada selección en vivo.

- **Repo:** `github.com/28jhoanleon/mlb-live-bets-bot`
- **Bot:** `@mlb_live_bets_bot`
- **Web:** `web-production-11c42.up.railway.app/?k=<WEB_KEY>`
- **Hosting:** Railway (un solo servicio corre bot + web en el mismo
  proceso, con volume montado en `/data`)
- **Desarrollo:** todo desde el celular, con Termux

## Cómo trabajamos

1. Se piden los cambios por chat
2. Llega un zip con la versión nueva
3. En Termux:
   ```bash
   cd ~/storage/downloads
   rm -rf mlb-live-bets-bot
   unzip -o mlb-live-bets-bot-vNN.zip
   bash mlb-live-bets-bot/limpiar_e_instalar.sh ~/storage/downloads/mlb-live-bets-bot
   cd ~/mlb-live-bets-bot && bash subir.sh
   ```
4. El `git push` dispara el deploy solo en Railway

`limpiar_e_instalar.sh` borra el código viejo y conserva `.env`, la base
de datos y el historial de git. `subir.sh` revisa que no se filtren
secretos, corre los tests y sube.

## Arquitectura

```
app/
  mlb/         cliente de MLB Stats API (schedule, live, players, pitchers)
  odds/        The Odds API (props y cuotas)
  ai/          visión: lee capturas de apuestas
  analysis/    tickets, probabilidad, tracking en vivo, combos, soñadoras
  bot/         handlers de Telegram (22 comandos)
  web/         API HTTP (Starlette) + la página
  db/          SQLite
  utils/       equipos, tiempo, barras, etiquetas de mercado
tests/         196 tests
```

Clave: `app/analysis` y `app/mlb` no saben nada de Telegram. El bot y la
web comparten esa lógica; solo cambia cómo la muestran.

## Cosas aprendidas a los golpes

- **No usar FastAPI**: arrastra pydantic, que compila Rust y falla en
  Termux. Se usa Starlette.
- **Hace falta `tzdata`**: sin ese paquete no hay zonas horarias en
  Termux, y el respaldo tiene que ser `timezone.utc` (no `ZoneInfo("UTC")`).
- **Escapar Markdown** en todo lo que venga de la IA: un `_` sin escapar
  hace que Telegram descarte el mensaje completo.
- **Las capturas vienen en español**: los mercados y las líneas ("Sobre
  3.5", "Golpes + Carreras + Carreras Remolcadas") se normalizan.
- **`isOnBench` de MLB miente**: da true para titulares que no están
  bateando en ese instante. Manda el orden de bateo.
- **Los Under solo se resuelven al final**: `actual < línea` es cierto
  desde el primer lanzamiento.
- **La API de Stake no sirve**: se investigó a fondo (introspección,
  sondeo por sugerencias, WebSocket). Las suscripciones solo traen
  números que cambian, ningún nombre de jugador ni mercado. Descartada.
- **Cuidado con editar por partes**: quedaron funciones duplicadas que
  se pisaban entre sí. Hay un test que lo detecta.

## Estado

Funcionando y probado en vivo: `/today`, `/live`, `/props`, `/value`,
lectura de capturas (una o varias), tracking en vivo, la web con logos y
horarios, partidos terminados con resultado congelado.

Construido pero poco probado: `/analyze`, `/compare`, `/sonadora`,
`/combos`, `/historial`, alertas automáticas.

Para agrupar varias capturas de una misma apuesta: etiqueta en el pie de
foto (un `1`, un `2`). Es la única señal confiable cuando la captura no
muestra el encabezado de la tarjeta.

## Pendiente

- Probar `/sonadora` (dio error de cuotas; el mensaje ahora dice la causa
  real: clave rechazada, consultas agotadas o props no publicadas)
- Vigilar el consumo de Railway (plan Trial)
- Regenerar el token de Stake, que quedó expuesto en el chat anterior
