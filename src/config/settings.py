"""
Configuración central de la aplicación.

Usa Pydantic BaseSettings para leer variables de entorno con tipado estricto.
Si una variable obligatoria (sin default) no está definida, la app falla al
arrancar con un error claro — mejor que un KeyError en runtime.

El decorador @lru_cache garantiza que Settings() se instancia una sola vez
(patrón singleton sin boilerplate) y se reutiliza en toda la aplicación.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    """Todas las variables de entorno del sistema, tipadas y validadas."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # MongoDB
    mongo_uri: str
    mongo_db: str = "seismic_db"

    # Redis
    redis_url: str = "redis://redis:6379/0"
    metrics_cache_ttl_seconds: int = 60

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_env: str = "development"

    # JWT
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 15
    jwt_refresh_token_expire_days: int = 7

    # Usuario seed (se crea en el startup de la API si no existe)
    seed_username: str = "admin"
    seed_password: str
    seed_email: str = "admin@seismic.local"

    # Ingesta USGS
    usgs_api_url: str = (
        "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_hour.geojson"
    )
    ingestion_interval_seconds: int = 180


@lru_cache
def get_settings() -> Settings:
    """Devuelve la instancia singleton de Settings. Usar como dependencia de FastAPI."""
    return Settings()
