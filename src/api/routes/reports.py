"""
Rutas de reportes horarios consolidados.

GET /reports — lista paginada de reportes generados por el DAG de Airflow.

Los reportes son inmutables — una vez generados por Airflow no se modifican.
Son un snapshot histórico de cada hora con datos enriquecidos (top locations, etc.)
"""

import structlog
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, Query
from motor.motor_asyncio import AsyncIOMotorDatabase

from src.database.mongodb import get_database
from src.database.repositories.report_repo import ReportRepository
from src.models.report import ReportListResponse, HourlyReportResponse
from src.api.dependencies import get_current_user

log = structlog.get_logger()
router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("", response_model=ReportListResponse)
async def get_reports(
    from_date: Optional[datetime] = Query(None, description="Desde (ISO 8601)"),
    to_date: Optional[datetime] = Query(None, description="Hasta (ISO 8601)"),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=50),
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> ReportListResponse:
    """
    Lista reportes horarios paginados, del más reciente al más antiguo.

    Filtros opcionales por rango de fechas para análisis histórico.
    """
    repo = ReportRepository(db)
    documents, total = await repo.find_many(
        from_date=from_date,
        to_date=to_date,
        page=page,
        page_size=page_size,
    )

    log.info("reports_fetched", total=total, page=page)

    return ReportListResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=[HourlyReportResponse(**doc) for doc in documents],
    )
