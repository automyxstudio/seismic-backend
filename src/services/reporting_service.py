"""
Servicio de generación de reportes horarios consolidados.

Usado exclusivamente por el DAG de Airflow — usa pymongo (driver síncrono)
porque Airflow no corre en un event loop async.

El resto del sistema (FastAPI, ingesta) usa Motor (async).
Esta es una excepción deliberada documentada en docs/decisiones.md (ADR-005).

Responsabilidades:
  - Leer todos los eventos de una ventana horaria específica.
  - Calcular: total, promedio, máximo, top 3 ubicaciones, distribución por rango.
  - Construir el HourlyReportDocument listo para persistir.
"""

from datetime import datetime, timezone
from collections import Counter

import structlog
import pymongo

from src.models.report import HourlyReportDocument
from src.models.metric import MagnitudeDistribution
from src.config.settings import get_settings

log = structlog.get_logger()


class ReportingService:
    """Genera reportes horarios consolidados desde los datos de MongoDB."""

    def __init__(self) -> None:
        settings = get_settings()
        # pymongo sync — requerido por el contexto síncrono de Airflow
        self._client = pymongo.MongoClient(settings.mongo_uri)
        self._db = self._client[settings.mongo_db]

    def close(self) -> None:
        """Cierra la conexión. Llamar al final de cada task de Airflow."""
        self._client.close()

    def read_events_for_hour(
        self, period_start: datetime, period_end: datetime
    ) -> list[dict]:
        """
        Lee todos los eventos sísmicos dentro del rango dado.

        Args:
            period_start: inicio de la ventana (inclusive).
            period_end: fin de la ventana (exclusive).

        Returns:
            Lista de documentos de la colección earthquakes.
        """
        cursor = self._db.earthquakes.find(
            {"event_time": {"$gte": period_start, "$lt": period_end}}
        )
        events = list(cursor)
        log.info(
            "report_events_read",
            count=len(events),
            period_start=period_start.isoformat(),
            period_end=period_end.isoformat(),
        )
        return events

    def generate_report(
        self,
        events: list[dict],
        period_start: datetime,
        period_end: datetime,
    ) -> HourlyReportDocument:
        """
        Calcula el reporte consolidado a partir de los eventos de una hora.

        Si no hay eventos, genera un reporte vacío (totals en cero).
        El reporte es idempotente: los mismos eventos producen el mismo reporte.

        Args:
            events: lista de documentos de earthquakes.
            period_start: inicio de la ventana horaria.
            period_end: fin de la ventana horaria.

        Returns:
            HourlyReportDocument listo para insertar en MongoDB.
        """
        if not events:
            log.warning("report_no_events", period_start=period_start.isoformat())
            return HourlyReportDocument(
                report_date=period_start,
                period_start=period_start,
                period_end=period_end,
                total_events=0,
                average_magnitude=0.0,
                max_magnitude=0.0,
                top_locations=[],
                magnitude_distribution=MagnitudeDistribution(),
            )

        magnitudes = [e["magnitude"] for e in events]
        total = len(events)
        avg_magnitude = round(sum(magnitudes) / total, 3)
        max_magnitude = max(magnitudes)

        # Top 3 ubicaciones por frecuencia
        location_counts = Counter(
            e.get("location", "Unknown") for e in events
        )
        top_locations = [loc for loc, _ in location_counts.most_common(3)]

        # Distribución por rango de magnitud
        distribution = MagnitudeDistribution()
        for event in events:
            mag_range = event.get("magnitude_range", "micro")
            current = getattr(distribution, mag_range, 0)
            setattr(distribution, mag_range, current + 1)

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

        log.info(
            "report_generated",
            total_events=total,
            avg_magnitude=avg_magnitude,
            max_magnitude=max_magnitude,
            top_locations=top_locations,
        )
        return report

    def save_report(self, report: HourlyReportDocument) -> str:
        """
        Persiste el reporte en la colección hourly_reports.

        Usa upsert por report_date para idempotencia: si el DAG se
        re-ejecuta por un fallo y retry, no crea documentos duplicados.

        Returns:
            ID del documento como string.
        """
        result = self._db.hourly_reports.update_one(
            {"report_date": report.report_date},
            {"$setOnInsert": report.model_dump()},
            upsert=True,
        )
        doc_id = str(result.upserted_id) if result.upserted_id else "already_exists"
        log.info("report_saved", report_date=str(report.report_date), id=doc_id)
        return doc_id
