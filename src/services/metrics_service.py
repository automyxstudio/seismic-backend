"""
Servicio de actualización de métricas y publicación en tiempo real.

Cuando la ingesta detecta un evento nuevo, llama a este servicio que:
  1. Actualiza la ventana horaria en MongoDB (conteo, max, distribución).
  2. Recalcula el promedio de magnitud para esa ventana.
  3. Publica el evento en el canal Redis para que los WebSockets lo retransmitan.
  4. Invalida el caché de métricas en Redis para que el próximo GET /metrics
     traiga datos frescos.
"""

import json
import structlog
from datetime import datetime, timezone

import redis.asyncio as aioredis
from motor.motor_asyncio import AsyncIOMotorDatabase

from src.models.earthquake import EarthquakeDocument
from src.database.repositories.metric_repo import MetricRepository
from src.database.repositories.earthquake_repo import EarthquakeRepository
from src.config.constants import REDIS_CHANNEL_NEW_EVENT, REDIS_KEY_METRICS_CURRENT

log = structlog.get_logger()


class MetricsService:
    """Actualiza métricas en MongoDB y notifica al WebSocket vía Redis."""

    def __init__(self, db: AsyncIOMotorDatabase, redis: aioredis.Redis) -> None:
        self.metric_repo = MetricRepository(db)
        self.earthquake_repo = EarthquakeRepository(db)
        self.redis = redis

    def _get_window(self, event_time: datetime) -> str:
        """
        Genera la clave de ventana horaria a partir del timestamp del evento.

        Ejemplo: datetime(2026, 6, 17, 10, 30) → '2026-06-17T10'
        """
        utc_time = event_time.astimezone(timezone.utc)
        return utc_time.strftime("%Y-%m-%dT%H")

    async def process_new_event(self, event: EarthquakeDocument) -> None:
        """
        Procesa un evento nuevo: actualiza métricas, publica en Redis.

        Args:
            event: evento sísmico recién insertado en MongoDB.
        """
        window = self._get_window(event.event_time)

        # 1. Actualizar conteo, distribución y magnitud máxima (atómico)
        await self.metric_repo.increment_window(
            window=window,
            magnitude=event.magnitude,
            magnitude_range=event.magnitude_range,
        )

        # 2. Recalcular promedio — requiere la magnitud del evento y el conteo actual
        await self._recalculate_avg(window, event.magnitude)

        # 3. Publicar en Redis → WebSocket lo retransmite a clientes conectados
        payload = json.dumps({
            "event_id": event.event_id,
            "magnitude": event.magnitude,
            "magnitude_range": event.magnitude_range.value,
            "location": event.location,
            "latitude": event.latitude,
            "longitude": event.longitude,
            "depth": event.depth,
            "event_time": event.event_time.isoformat(),
        })
        await self.redis.publish(REDIS_CHANNEL_NEW_EVENT, payload)

        # 4. Invalidar caché de métricas para que el próximo GET /metrics sea fresco
        await self.redis.delete(REDIS_KEY_METRICS_CURRENT)

        log.info(
            "metrics_updated",
            event_id=event.event_id,
            window=window,
            magnitude=event.magnitude,
        )

    async def _recalculate_avg(self, window: str, new_magnitude: float) -> None:
        """
        Recalcula el promedio de magnitud usando la fórmula incremental.

        avg_new = avg_old + (new_value - avg_old) / n

        Evita sumar todos los eventos históricos — solo necesita el promedio
        anterior, la nueva magnitud y el conteo actualizado (ya incrementado
        por increment_window antes de llamar aquí).

        Args:
            window: clave de la ventana horaria.
            new_magnitude: magnitud del evento que acaba de ser procesado.
        """
        metric = await self.metric_repo.find_by_window(window)
        if not metric:
            return

        count = metric["earthquake_count"]
        current_avg = metric.get("avg_magnitude", 0.0)

        # Fórmula incremental: O(1) en tiempo y memoria
        new_avg = current_avg + (new_magnitude - current_avg) / count

        await self.metric_repo.update_avg_magnitude(window, round(new_avg, 3))
