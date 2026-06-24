"""
Modelos Pydantic para reportes horarios consolidados.

Los reportes son generados por el DAG de Airflow cada hora.
A diferencia de las métricas (actualizadas en tiempo real por la ingesta),
los reportes son snapshots inmutables que consolidan los eventos de una
ventana horaria completa con información enriquecida (top locations, etc.).
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
from src.models.metric import MagnitudeDistribution


class HourlyReportDocument(BaseModel):
    """
    Reporte consolidado de una hora completa, generado por Airflow.

    Se almacena en la colección 'hourly_reports'. Una vez creado, no se
    modifica — es un registro histórico inmutable.
    """

    report_date: datetime
    """Timestamp de inicio de la hora reportada (e.g. 2026-06-17T10:00:00Z)."""

    period_start: datetime
    period_end: datetime
    total_events: int
    average_magnitude: float
    max_magnitude: float

    top_locations: list[str]
    """Las 3 ubicaciones con más sismos en la hora, ordenadas por frecuencia."""

    magnitude_distribution: MagnitudeDistribution
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    generated_by: str = "airflow_dag"


class HourlyReportResponse(BaseModel):
    """Representación del reporte para la API REST."""

    id: Optional[str] = Field(None, alias="_id")
    report_date: datetime
    period_start: datetime
    period_end: datetime
    total_events: int
    average_magnitude: float
    max_magnitude: float
    top_locations: list[str]
    magnitude_distribution: MagnitudeDistribution
    generated_at: datetime

    model_config = {"populate_by_name": True}


class ReportListResponse(BaseModel):
    """Respuesta paginada para GET /reports."""

    total: int
    page: int
    page_size: int
    items: list[HourlyReportResponse]
