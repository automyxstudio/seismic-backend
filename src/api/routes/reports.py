"""
Rutas de reportes horarios consolidados.

GET  /reports         — lista paginada de reportes generados por el DAG de Airflow.
POST /reports/trigger — genera un reporte de la hora actual de forma inmediata.

Los reportes son inmutables — una vez generados por Airflow no se modifican.
Son un snapshot histórico de cada hora con datos enriquecidos (top locations, etc.)
"""

import structlog
from collections import Counter
from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase

from src.database.mongodb import get_database
from src.database.repositories.report_repo import ReportRepository
from src.services.reporting_service import ReportingService
from src.models.report import ReportListResponse, HourlyReportResponse, HourlyReportDocument
from src.models.metric import MagnitudeDistribution
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


@router.post("/trigger", tags=["reports"])
async def trigger_report(
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> dict:
    """
    Genera el reporte de la hora actual de forma inmediata, sin esperar a Airflow.

    Usa Motor (async) para leer y persistir — misma lógica de cálculo que el DAG.
    Idempotente: si ya existe un reporte para esta hora, lo sobreescribe.
    """
    now = datetime.now(timezone.utc)
    period_start = now.replace(minute=0, second=0, microsecond=0)
    period_end = period_start + timedelta(hours=1)

    try:
        # Leer eventos de la ventana horaria actual con Motor (async)
        cursor = db.earthquakes.find(
            {"event_time": {"$gte": period_start, "$lt": period_end}}
        )
        events = await cursor.to_list(length=None)

        if not events:
            raise HTTPException(
                status_code=404,
                detail="No hay eventos registrados en la hora actual para generar un reporte",
            )

        # Calcular reporte — lógica pura, sin I/O (idéntica al DAG de Airflow)
        magnitudes = [e["magnitude"] for e in events]
        total = len(events)
        avg_magnitude = round(sum(magnitudes) / total, 3)
        max_magnitude = max(magnitudes)

        location_counts = Counter(e.get("location", "Unknown") for e in events)
        top_locations = [loc for loc, _ in location_counts.most_common(3)]

        distribution = MagnitudeDistribution()
        for event in events:
            mag_range = event.get("magnitude_range", "micro")
            setattr(distribution, mag_range, getattr(distribution, mag_range, 0) + 1)

        report = HourlyReportDocument(
            report_date=period_start,
            period_start=period_start,
            period_end=period_end,
            total_events=total,
            average_magnitude=avg_magnitude,
            max_magnitude=max_magnitude,
            top_locations=top_locations,
            magnitude_distribution=distribution,
        )

        # Persistir con upsert — idempotente si se llama varias veces en la misma hora
        await db.hourly_reports.update_one(
            {"report_date": period_start},
            {"$set": report.model_dump()},
            upsert=True,
        )

        log.info("report_triggered_manually", period=str(period_start), total_events=total)
        return {
            "status": "ok",
            "period": period_start.isoformat(),
            "total_events": total,
            "avg_magnitude": avg_magnitude,
            "max_magnitude": max_magnitude,
            "top_locations": top_locations,
        }

    except HTTPException:
        raise
    except Exception as e:
        log.error("report_trigger_error", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error generando reporte: {str(e)}")
