"""
Gestión del ciclo de vida de la conexión a Redis.

Usa el cliente async de la librería redis-py con connection pool interno.
Se inicializa una sola vez en el startup y se reutiliza en toda la app.

Redis cumple dos roles en este sistema:
  1. Caché: almacena resultados de métricas con TTL para evitar queries repetidas.
  2. Pub/Sub: canal 'seismic:new_event' para notificar al WebSocket de eventos nuevos.
"""

import redis.asyncio as aioredis
from src.config.settings import get_settings

_redis: aioredis.Redis | None = None


async def connect_to_redis() -> None:
    """
    Abre la conexión a Redis con pool de conexiones.
    Llamar en el startup de la app.
    """
    global _redis
    settings = get_settings()
    _redis = aioredis.from_url(
        settings.redis_url,
        encoding="utf-8",
        decode_responses=True,
    )
    # Ping para verificar conectividad
    await _redis.ping()


async def close_redis_connection() -> None:
    """Cierra la conexión a Redis. Llamar en el shutdown de la app."""
    global _redis
    if _redis:
        await _redis.aclose()
        _redis = None


def get_redis() -> aioredis.Redis:
    """
    Devuelve la instancia de Redis.
    Se usa como dependencia de FastAPI: Depends(get_redis).
    """
    if _redis is None:
        raise RuntimeError("Redis no está conectado. Llamar connect_to_redis() primero.")
    return _redis
