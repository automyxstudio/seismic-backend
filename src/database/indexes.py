"""
Creación de índices en MongoDB.

Se ejecuta una vez en el startup de la app.
Si los índices ya existen, MongoDB los ignora silenciosamente — es seguro
llamar esta función en cada arranque sin riesgo de duplicar índices.

Los índices están justificados en docs/arquitectura.md.
Resumen de la estrategia:
  - event_id único: deduplicación a nivel de BD (segunda línea tras el upsert).
  - event_time desc: queries de rango temporal (últimas N horas).
  - magnitude: filtros y ordenamiento por magnitud.
  - window único en metrics: una doc por ventana horaria.
  - report_date único en hourly_reports: un reporte por hora.
"""

import structlog
from pymongo import ASCENDING, DESCENDING
from motor.motor_asyncio import AsyncIOMotorDatabase

log = structlog.get_logger()


async def create_indexes(db: AsyncIOMotorDatabase) -> None:
    """
    Crea todos los índices necesarios en las colecciones.

    Args:
        db: instancia de la base de datos Motor.
    """
    await _create_earthquake_indexes(db)
    await _create_metric_indexes(db)
    await _create_report_indexes(db)
    await _create_user_indexes(db)
    log.info("indexes_created", status="ok")


async def _create_earthquake_indexes(db: AsyncIOMotorDatabase) -> None:
    """Índices de la colección earthquakes."""
    col = db.earthquakes

    # Clave de negocio única — base de la deduplicación
    await col.create_index("event_id", unique=True, name="idx_event_id_unique")

    # Queries de rango temporal (e.g. "sismos de la última hora")
    await col.create_index(
        [("event_time", DESCENDING)], name="idx_event_time_desc"
    )

    # Filtros y ordenamiento por magnitud
    await col.create_index(
        [("magnitude", ASCENDING)], name="idx_magnitude_asc"
    )

    # Filtro por categoría de magnitud (micro, menor, ligero, etc.)
    await col.create_index("magnitude_range", name="idx_magnitude_range")

    # Queries geoespaciales por región (e.g. "sismos cerca de X")
    await col.create_index(
        [("latitude", ASCENDING), ("longitude", ASCENDING)],
        name="idx_geo"
    )


async def _create_metric_indexes(db: AsyncIOMotorDatabase) -> None:
    """Índices de la colección metrics."""
    col = db.metrics

    # Una doc por ventana horaria — clave del modelo de métricas
    await col.create_index("window", unique=True, name="idx_window_unique")

    # Obtener la ventana más reciente eficientemente
    await col.create_index(
        [("updated_at", DESCENDING)], name="idx_updated_at_desc"
    )


async def _create_report_indexes(db: AsyncIOMotorDatabase) -> None:
    """Índices de la colección hourly_reports."""
    col = db.hourly_reports

    # Un reporte por hora
    await col.create_index("report_date", unique=True, name="idx_report_date_unique")

    # Obtener el reporte más reciente
    await col.create_index(
        [("generated_at", DESCENDING)], name="idx_generated_at_desc"
    )


async def _create_user_indexes(db: AsyncIOMotorDatabase) -> None:
    """Índices de la colección users."""
    col = db.users

    await col.create_index("username", unique=True, name="idx_username_unique")
    await col.create_index("email", unique=True, name="idx_email_unique")
