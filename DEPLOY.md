# Poner todo en línea (Railway)

Al terminar esto vas a tener:

- El bot corriendo **24/7**, sin depender de que Termux esté abierto
- Las **alertas automáticas** funcionando de verdad (hoy solo corren
  mientras tenés el celular con la app abierta)
- La **web** con tus apuestas en vivo, accesible desde cualquier lado

Todo en un solo servicio: mismo proceso, misma base de datos, misma
lógica. Un solo lugar donde mirar si algo falla.

---

## 1. Subir el código a GitHub

Railway lee el proyecto desde GitHub, así que este paso es obligatorio.

Desde Termux:

```bash
cd ~/mlb-live-bets-bot
git add .
git commit -m "Bot + web con seguimiento en vivo"
git push
```

Si pide usuario y contraseña: el usuario es tu nombre de GitHub, y la
contraseña es un **token** (GitHub ya no acepta la contraseña normal).
Se genera en: Settings → Developer settings → Personal access tokens →
Tokens (classic) → Generate new token → marcar `repo`.

Antes de subir, confirmá que el `.env` NO va incluido:

```bash
git status
```

No tiene que aparecer `.env` en la lista. Si aparece, avisá antes de
seguir: tus claves quedarían públicas.

---

## 2. Crear el servicio en Railway

1. Entrá a [railway.app](https://railway.app) e iniciá sesión con GitHub
2. **New Project** → **Deploy from GitHub repo**
3. Elegí `mlb-live-bets-bot`
4. Railway detecta Python solo y empieza a construir

El primer intento va a fallar porque faltan las variables. Es lo
esperado, se arregla en el paso siguiente.

---

## 3. Cargar las variables

En el servicio → pestaña **Variables** → agregá una por una:

| Variable | Valor |
|---|---|
| `BOT_TOKEN` | El de BotFather |
| `ODDS_API_KEY` | El de the-odds-api.com |
| `OPENAI_API_KEY` | El de platform.openai.com |
| `OWNER_CHAT_ID` | Mandá `/miid` al bot y te lo dice |
| `WEB_KEY` | Inventá una clave larga, ej. `xk92mfp3qz7` |
| `TZ_NAME` | `America/Argentina/Buenos_Aires` |

> Estas son claves nuevas, ¿no? Las que usamos durante el desarrollo
> quedaron expuestas en el chat. Regeneralas antes de cargarlas acá.

Al guardar, Railway redespliega solo.

---

## 4. Abrir la web al público

Por defecto el servicio no es accesible desde afuera.

**Settings** → **Networking** → **Generate Domain**

Te da una dirección tipo `mlb-live-bets-bot-production.up.railway.app`.

Tu web es esa dirección **más tu clave**:

```
https://TU-DOMINIO.up.railway.app/?k=TU_WEB_KEY
```

Guardala en los favoritos del celular. Mejor: abrila en Chrome →
menú ⋮ → **Agregar a pantalla principal**. Queda como una app.

---

## 5. Comprobar que anda

```
https://TU-DOMINIO.up.railway.app/health
```

Tiene que responder `{"ok":true}`.

Después, en Telegram mandale `/start` al bot. Si contesta, está vivo en
el servidor.

---

## Detalles que conviene saber

**La base de datos se borra en cada deploy.** Railway usa disco
efímero: cada vez que subas cambios, se pierden el historial y las
apuestas guardadas. Para que persista hay que agregar un **Volume**
(Settings → Volumes, montado en `/data`) y poner
`DATABASE_URL=sqlite:////data/mlb_bets.db`.

**Podés apagar Termux.** Una vez que Railway está corriendo, el bot vive
allá. Si dejás los dos prendidos a la vez, Telegram se confunde con dos
instancias pidiendo los mismos mensajes: dejá solo uno.

**Los costos.** Railway tiene un plan gratuito con horas limitadas por
mes. Un proceso liviano como este suele entrar, pero conviene mirar el
consumo la primera semana.

**Para actualizar** de ahora en más alcanza con:

```bash
git add . && git commit -m "cambios" && git push
```

Railway detecta el push y redespliega solo.
