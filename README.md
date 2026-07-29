# MLB Live Bets AI

Asistente de apuestas MLB por Telegram. Analiza partidos, props, capturas
de apuestas (simples y combinadas), y da probabilidad real basada en
stats — no solo lista partidos.

## Setup local (Termux / cualquier Linux)

```bash
pip install -r requirements.txt
cp .env.example .env   # completar con tus keys reales
python main.py
```

## Variables de entorno necesarias (`.env`)

- `BOT_TOKEN` — de @BotFather
- `ODDS_API_KEY` — de the-odds-api.com (tiene free tier)
- `OPENAI_API_KEY` — de platform.openai.com (necesita crédito cargado)

## Comandos

- `/today` — partidos de hoy, pitchers probables, hora, estadio
- `/live` — partidos en curso
- `/props` — props disponibles (hits, HR) por partido
- `/value` — detecta +EV cruzando cuotas entre casas
- `/refresh` — recalcula la última apuesta analizada sin pedir la foto de nuevo
- 📸 Mandale una foto de una apuesta (Bet365, Stake, etc.) para análisis automático

## Deploy en Railway

El repo incluye `Procfile` y `railway.json`. Es un *worker* (usa polling,
no expone puerto HTTP), así que al crear el servicio en Railway hay que
configurarlo como Worker, no como Web Service. Cargar las mismas 3
variables de entorno de arriba en Railway → Variables.

## Estado / limitaciones conocidas

- No hay persistencia en base de datos todavía — `/refresh` y el
  historial se pierden si el bot se reinicia.
- El análisis de "sigue en cancha" es confiable para pitchers, best-effort
  para bateadores (la API no siempre marca sustituciones con claridad).
- La probabilidad combinada de una combinada asume independencia entre
  legs — si son del mismo partido, la realidad puede ser algo mejor por
  correlación.
