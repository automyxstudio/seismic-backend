"""
Repositorio para la colección 'hourly_reports'.

Los reportes son documentos inmutables generados por Airflow.
Una vez creado un reporte para una hora, no se modifica.
"""

import structlog
from datetime import datetime
from pymongo import DESCENDING
from motor.motor_asyncio import AsyncIOMotorDatabase

from src.models.report import HourlyReportDocument

log = structlog.get_logger()


class ReportRepository:
    """Operaciones de lectura y escritura sobre la colección hourly_reports."""

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self.collection = db.hourly_reports

    async def insert(self, report: HourlyReportDocument) -> str:
        """
        Inserta un nuevo reporte horario.

        Usa upsert por report_date para idempotencia: si el DAG se
        re-ejecuta para la misma hora (por fallo y retry), no crea duplicados.

        Returns:
            ID del documento insertado o actualizado.
        """
        result = await self.collection.update_one(
            {"report_date": report.report_date},
            {"$setOnInsert": report.model_dump()},
            upsert=True,
        )
        doc_id = str(result.upserted_id) if result.upserted_id else "already_exists"
        log.info("report_saved", report_date=str(report.report_date), id=doc_id)
        return doc_id

    async def find_many(
        self,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
        page: int = 1,
        page_size: int = 10,
    ) -> tuple[list[dict], int]:
        """
        Retorna reportes paginados con filtro opcional por rango de fechas.
        Usado por GET /reports.
        """
        query: dict = {}
        if from_date or to_date:
            query["report_date"] = {}
            if from_date:
                query["report_date"]["$gte"] = from_date
            if to_date:
                query["report_date"]["$lte"] = to_date

        total = await self.collection.count_documents(query)
        skip = (page - 1) * page_size

        cursor = (
            self.collection.find(query)
            .sort("report_date", DESCENDING)
            .skip(skip)
            .limit(page_size)
        )
        documents = await cursor.to_list(length=page_size)
        for doc in documents:
            doc["_id"] = str(doc["_id"])
        return documents, total
