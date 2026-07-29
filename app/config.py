"""Configuración central del bot. Todo lo que sea 'secreto' o 'ajustable'
vive acá, leído desde variables de entorno (.env en local, Railway vars
en producción)."""
import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()  # No-op en Railway (no hay .env), útil en Termux/local


@dataclass(frozen=True)
class Settings:
    # Telegram
    bot_token: str = os.getenv("BOT_TOKEN", "")

    # MLB Stats API (pública, no requiere key)
    mlb_stats_base_url: str = os.getenv(
        "MLB_STATS_BASE_URL", "https://statsapi.mlb.com/api/v1"
    )

    # Odds provider — intercambiable. Empezamos con The Odds API.
    odds_provider: str = os.getenv("ODDS_PROVIDER", "the_odds_api")
    odds_api_key: str = os.getenv("ODDS_API_KEY", "")
    # Casas donde el usuario realmente juega. Se usan para PRIORIZAR qué
    # apuestas mostrar, no para calcular la probabilidad justa: esa se
    # sigue calculando con todas las casas disponibles, porque un
    # consenso de 2 casas no es un consenso.
    # Vacío = mostrar todas.
    preferred_bookmakers: str = os.getenv("PREFERRED_BOOKMAKERS", "")

    @property
    def preferred_books(self) -> list[str]:
        return [b.strip().lower() for b in self.preferred_bookmakers.split(",") if b.strip()]

    # IA multimodal (análisis de capturas)
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_vision_model: str = os.getenv("OPENAI_VISION_MODEL", "gpt-4o")

    # Base de datos
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///mlb_bets.db")

    # Logging
    log_level: str = os.getenv("LOG_LEVEL", "INFO")

    # Timezone de referencia para horarios de partidos
    timezone: str = os.getenv("TZ_NAME", "America/Argentina/Buenos_Aires")

    def validate(self) -> None:
        """Falla rápido y claro si falta algo crítico, en vez de romper
        más adelante con un error críptico."""
        if not self.bot_token:
            raise RuntimeError(
                "Falta BOT_TOKEN. Definilo en .env (local) o en las "
                "variables de entorno de Railway."
            )


settings = Settings()
