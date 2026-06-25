"""
Rutas de eventos sísmicos.

GET /earthquakes — lista paginada con filtros opcionales por magnitud,
                   rango de magnitud, rango de fechas y ordenamiento.

Todos los parámetros son validados automáticamente por Pydantic/FastAPI.
Un valor inválido (e.g. page=-1) retorna 422 con el error exacto.
"""

import structlog
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, Query
from pymongo import ASCENDING, DESCENDING
from motor.motor_asyncio import AsyncIOMotorDatabase

from src.database.mongodb import get_database
from src.database.repositories.earthquake_repo import EarthquakeRepository
from src.models.earthquake import EarthquakeListResponse, EarthquakeResponse
from src.config.constants import MagnitudeRange
from src.api.dependencies import get_current_user

log = structlog.get_logger()
router = APIRouter(prefix="/earthquakes", tags=["earthquakes"])


@router.get("", response_model=EarthquakeListResponse)
async def get_earthquakes(
    # Filtros por magnitud
    magnitude_min: Optional[float] = Query(None, ge=0, description="Magnitud mínima"),
    magnitude_max: Optional[float] = Query(None, ge=0, description="Magnitud máxima"),
    magnitude_range: Optional[MagnitudeRange] = Query(None, description="Rango de magnitud"),
    # Filtros por fecha
    from_date: Optional[datetime] = Query(None, description="Desde (ISO 8601)"),
    to_date: Optional[datetime] = Query(None, description="Hasta (ISO 8601)"),
    # Paginación
    page: int = Query(1, ge=1, description="Número de página"),
    page_size: int = Query(20, ge=1, le=100, description="Elementos por página"),
    # Ordenamiento
    sort_by: str = Query("event_time", description="Campo por el que ordenar"),
    order: str = Query("desc", pattern="^(asc|desc)$", description="asc o desc"),
    # Auth
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> EarthquakeListResponse:
    """
    Lista eventos sísmicos con filtros, paginación y ordenamiento.

    Todos los parámetros son opcionales — sin filtros retorna los más recientes.
    """
    mongo_order = DESCENDING if order == "desc" else ASCENDING

    repo = EarthquakeRepository(db)
    documents, total = await repo.find_many(
        magnitude_min=magnitude_min,
        magnitude_max=magnitude_max,
        magnitude_range=magnitude_range,
        from_date=from_date,
        to_date=to_date,
        sort_by=sort_by,
        order=mongo_order,
        page=page,
        page_size=page_size,
    )

    log.info(
        "earthquakes_fetched",
        total=total,
        page=page,
        filters={
            "magnitude_min": magnitude_min,
            "magnitude_max": magnitude_max,
            "magnitude_range": magnitude_range,
        },
    )

    return EarthquakeListResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=[EarthquakeResponse(**doc) for doc in documents],
    )
