"""
Rutas de métricas sísmicas por ventana horaria.

GET /metrics — retorna las últimas N ventanas con sus métricas agregadas.

Implementa caché en Redis con TTL de 60 segundos para evitar recalcular
en cada request. El MetricsService invalida el caché cuando llega un evento nuevo,
garantizando que los datos nunca estén desactualizados más de 60 segundos.
"""

import json
import structlog
from fastapi import APIRouter, Depends, Query
from motor.motor_asyncio import AsyncIOMotorDatabase
import redis.asyncio as aioredis

from src.database.mongodb import get_database
from src.database.redis import get_redis
from src.database.repositories.metric_repo import MetricRepository
from src.models.metric import MetricResponse
from src.api.dependencies import get_current_user
from src.config.constants import REDIS_KEY_METRICS_CURRENT
from src.config.settings import get_settings

log = structlog.get_logger()
router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("", response_model=list[MetricResponse])
async def get_metrics(
    limit: int = Query(24, ge=1, le=168, description="Últimas N horas (max 168 = 7 días)"),
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_database),
    redis: aioredis.Redis = Depends(get_redis),
) -> list[MetricResponse]:
    """
    Retorna métricas agregadas por ventana horaria.

    Estrategia de caché:
      1. Buscar en Redis (clave: seismic:metrics:current).
      2. Cache hit  → deserializar y retornar directamente.
      3. Cache miss → consultar MongoDB, guardar en Redis con TTL 60s y retornar.
    """
    settings = get_settings()
    cache_key = f"{REDIS_KEY_METRICS_CURRENT}:{limit}"

    # Intentar cache hit
    cached = await redis.get(cache_key)
    if cached:
        log.info("metrics_cache_hit", key=cache_key)
        return [MetricResponse(**item) for item in json.loads(cached)]

    # Cache miss — consultar MongoDB
    log.info("metrics_cache_miss", key=cache_key)
    repo = MetricRepository(db)
    documents = await repo.find_recent(limit=limit)

    # Guardar en Redis con TTL
    await redis.setex(
        cache_key,
        settings.metrics_cache_ttl_seconds,
        json.dumps(documents, default=str),
    )

    return [MetricResponse(**doc) for doc in documents]
