"""
Repositorio para la colección 'earthquakes'.

Centraliza toda la lógica de acceso a datos de eventos sísmicos.
Los servicios nunca escriben queries de MongoDB directamente —
pasan por este repositorio. Esto facilita testear los servicios
con un repositorio mock sin tocar la base de datos real.
"""

import structlog
from datetime import datetime
from typing import Optional
from pymongo import DESCENDING
from motor.motor_asyncio import AsyncIOMotorDatabase

from src.models.earthquake import EarthquakeDocument, EarthquakeResponse
from src.config.constants import MagnitudeRange

log = structlog.get_logger()


class EarthquakeRepository:
    """Operaciones de lectura y escritura sobre la colección earthquakes."""

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self.collection = db.earthquakes

    async def upsert(self, event: EarthquakeDocument) -> bool:
        """
        Inserta el evento si no existe. Si ya existe, no hace nada.

        Usa $setOnInsert para que un evento duplicado no sobreescriba
        el documento existente. Es atómico — sin race conditions.

        Returns:
            True si el documento era nuevo, False si ya existía.
        """
        result = await self.collection.update_one(
            {"event_id": event.event_id},
            {"$setOnInsert": event.model_dump()},
            upsert=True,
        )
        is_new = result.upserted_id is not None
        if is_new:
            log.info("earthquake_inserted", event_id=event.event_id, magnitude=event.magnitude)
        return is_new

    async def find_many(
        self,
        magnitude_min: Optional[float] = None,
        magnitude_max: Optional[float] = None,
        magnitude_range: Optional[MagnitudeRange] = None,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        sort_by: str = "event_time",
        order: int = DESCENDING,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict], int]:
        """
        Busca eventos con filtros opcionales, paginación y ordenamiento.

        Returns:
            Tupla (lista de documentos, total de documentos que coinciden).
        """
        query: dict = {}

        if magnitude_min is not None or magnitude_max is not None:
            query["magnitude"] = {}
            if magnitude_min is not None:
                query["magnitude"]["$gte"] = magnitude_min
            if magnitude_max is not None:
                query["magnitude"]["$lte"] = magnitude_max

        if magnitude_range:
            query["magnitude_range"] = magnitude_range.value

        if from_date or to_date:
            query["event_time"] = {}
            if from_date:
                query["event_time"]["$gte"] = from_date
            if to_date:
                query["event_time"]["$lte"] = to_date

        total = await self.collection.count_documents(query)
        skip = (page - 1) * page_size

        cursor = (
            self.collection.find(query)
            .sort(sort_by, order)
            .skip(skip)
            .limit(page_size)
        )
        documents = await cursor.to_list(length=page_size)

        # Convertir _id de ObjectId a string
        for doc in documents:
            doc["_id"] = str(doc["_id"])

        return documents, total

    async def find_by_time_range(
        self, start: datetime, end: datetime
    ) -> list[dict]:
        """
        Retorna todos los eventos en un rango de tiempo.
        Usado por el DAG de Airflow para generar reportes horarios.
        """
        cursor = self.collection.find(
            {"event_time": {"$gte": start, "$lt": end}}
        )
        documents = await cursor.to_list(length=None)
        for doc in documents:
            doc["_id"] = str(doc["_id"])
        return documents
