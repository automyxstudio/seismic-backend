"""
Repositorio para la colección 'metrics'.

Las métricas se actualizan de forma atómica con operadores de MongoDB ($inc, $max, $set)
para evitar leer el documento antes de escribirlo (patrón read-modify-write),
que es vulnerable a race conditions en entornos concurrentes.
"""

import structlog
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import DESCENDING, ReturnDocument

from src.models.metric import MetricDocument
from src.config.constants import MagnitudeRange

log = structlog.get_logger()


class MetricRepository:
    """Operaciones de lectura y escritura sobre la colección metrics."""

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self.collection = db.metrics

    async def increment_window(
        self,
        window: str,
        magnitude: float,
        magnitude_range: MagnitudeRange,
    ) -> None:
        """
        Actualiza atómicamente las métricas de una ventana horaria.

        Usa $inc para el conteo, $max para la magnitud máxima y
        $set para el timestamp. Todo en una sola operación — sin leer primero.

        Args:
            window: clave de la ventana (e.g. '2026-06-17T10').
            magnitude: magnitud del nuevo evento.
            magnitude_range: categoría del nuevo evento.
        """
        distribution_field = f"magnitude_distribution.{magnitude_range.value}"

        await self.collection.update_one(
            {"window": window},
            {
                "$inc": {
                    "earthquake_count": 1,
                    distribution_field: 1,
                },
                "$max": {"max_magnitude": magnitude},
                "$set": {"updated_at": datetime.utcnow()},
            },
            upsert=True,
        )

    async def update_avg_magnitude(self, window: str, avg: float) -> None:
        """
        Actualiza el promedio de magnitud de una ventana.

        El promedio no puede calcularse con $inc — requiere conocer el total acumulado.
        Se llama después de cada inserción desde el metrics_service.
        """
        await self.collection.update_one(
            {"window": window},
            {"$set": {"avg_magnitude": avg, "updated_at": datetime.utcnow()}},
        )

    async def find_recent(self, limit: int = 24) -> list[dict]:
        """
        Retorna las últimas N ventanas horarias, ordenadas de más reciente a más antigua.
        Usado por GET /metrics.
        """
        cursor = (
            self.collection.find()
            .sort("window", DESCENDING)
            .limit(limit)
        )
        documents = await cursor.to_list(length=limit)
        for doc in documents:
            doc["_id"] = str(doc["_id"])
        return documents

    async def find_by_window(self, window: str) -> dict | None:
        """Busca una ventana horaria específica por su clave."""
        doc = await self.collection.find_one({"window": window})
        if doc:
            doc["_id"] = str(doc["_id"])
        return doc
