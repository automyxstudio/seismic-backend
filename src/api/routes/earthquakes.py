"""
Rutas de eventos sísmicos.

GET /earthquakes — lista paginada con filtros opcionales por magnitud,
                   rango de magnitud, rango de fechas y ordenamiento.

Todos los parámetros son validados automáticamente por Pydantic/FastAPI.
Un valor inválido (e.g. page=-1) retorna 422 con el error exacto.
"""

import json
import random
import uuid
import structlog
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from pymongo import ASCENDING, DESCENDING
from motor.motor_asyncio import AsyncIOMotorDatabase

from src.database.mongodb import get_database
from src.database.redis import get_redis
from src.database.repositories.earthquake_repo import EarthquakeRepository
from src.services.processing_service import ProcessingService
from src.services.metrics_service import MetricsService
from src.clients.usgs_client import USGSClient
from src.models.earthquake import EarthquakeListResponse, EarthquakeResponse, EarthquakeDocument
from src.config.constants import MagnitudeRange, classify_magnitude, REDIS_CHANNEL_NEW_EVENT
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


# Coordenadas de zonas sísmicas reales para que el marcador aparezca en una ubicación verosímil
_DEMO_LOCATIONS = [
    (37.7749, -122.4194, "San Francisco, California"),
    (35.6762, 139.6503, "Tokyo, Japan"),
    (-33.4489, -70.6693, "Santiago, Chile"),
    (19.4326, -99.1332, "Ciudad de México, Mexico"),
    (38.9072, -77.0369, "Washington DC, USA"),
    (-6.2088, 106.8456, "Jakarta, Indonesia"),
    (28.6139, 77.2090, "New Delhi, India"),
    (41.0082, 28.9784, "Istanbul, Turkey"),
    (37.3861, -122.0839, "Silicon Valley, California"),
    (-12.0464, -77.0428, "Lima, Peru"),
]


@router.post("/simulate", response_model=EarthquakeResponse, tags=["earthquakes"])
async def simulate_earthquake(
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> EarthquakeResponse:
    """
    Genera un sismo sintético aleatorio y lo inyecta en el pipeline completo.

    Flujo: genera evento → guarda en MongoDB → publica en Redis → WebSocket lo
    retransmite a todos los clientes conectados en tiempo real.

    Útil para demo: permite ver el mapa y el feed actualizarse sin esperar
    a que ocurra un sismo real en la ventana de 3 minutos de la ingesta.
    """
    # Magnitud aleatoria con distribución realista (más sismos pequeños que grandes)
    magnitude = round(random.uniform(1.0, 7.5), 1)
    lat_base, lon_base, place = random.choice(_DEMO_LOCATIONS)

    # Pequeña variación de coordenadas para que no aparezcan todos en el mismo punto
    latitude = round(lat_base + random.uniform(-1.5, 1.5), 4)
    longitude = round(lon_base + random.uniform(-1.5, 1.5), 4)
    depth = round(random.uniform(5.0, 70.0), 1)

    event = EarthquakeDocument(
        event_id=f"sim-{uuid.uuid4().hex[:12]}",
        magnitude=magnitude,
        magnitude_range=classify_magnitude(magnitude),
        location=f"{random.randint(5, 80)} km {'NW' if random.random() > 0.5 else 'SE'} of {place}",
        latitude=latitude,
        longitude=longitude,
        depth=depth,
        event_time=datetime.now(timezone.utc),
    )

    # Persistir en MongoDB (aparece en GET /earthquakes)
    doc = event.model_dump()
    result = await db.earthquakes.insert_one(doc)
    doc["_id"] = str(result.inserted_id)

    redis = get_redis()

    # Actualizar métricas — mismo paso que hace la ingesta automática
    # Esto actualiza los contadores en MongoDB y el caché Redis de métricas
    await MetricsService(db=db, redis=redis).process_new_event(event)

    # Publicar en Redis → el WebSocket lo retransmite a todos los clientes
    payload = {
        "id": doc["_id"],
        "event_id": event.event_id,
        "magnitude": event.magnitude,
        "magnitude_range": event.magnitude_range,
        "location": event.location,
        "latitude": event.latitude,
        "longitude": event.longitude,
        "depth": event.depth,
        "event_time": event.event_time.isoformat(),
        "ingested_at": event.ingested_at.isoformat(),
    }
    await redis.publish(REDIS_CHANNEL_NEW_EVENT, json.dumps(payload))

    log.info(
        "earthquake_simulated",
        event_id=event.event_id,
        magnitude=event.magnitude,
        magnitude_range=event.magnitude_range,
        location=event.location,
    )

    return EarthquakeResponse(**doc)


@router.post("/sync", tags=["earthquakes"])
async def sync_from_usgs(
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> dict:
    """
    Dispara un ciclo de ingesta manual desde la API de USGS.

    Ejecuta el mismo pipeline que el servicio de ingesta automático:
    fetch → transform → upsert (deduplicado) → métricas → Redis pub/sub.

    Útil para forzar una sincronización sin esperar los 3 minutos del loop.
    Los eventos ya existentes se ignoran gracias al upsert idempotente.
    """
    try:
        redis = get_redis()
        raw_features = await USGSClient().fetch_earthquakes()

        if not raw_features:
            return {"status": "ok", "fetched": 0, "new": 0, "message": "USGS no reporta sismos en la última hora"}

        processing = ProcessingService()
        repo = EarthquakeRepository(db)
        metrics = MetricsService(db=db, redis=redis)

        events = processing.transform_many(raw_features)

        new_count = 0
        for event in events:
            is_new = await repo.upsert(event)
            if is_new:
                await metrics.process_new_event(event)
                new_count += 1

        log.info("manual_sync_done", fetched=len(raw_features), valid=len(events), new=new_count)
        return {
            "status": "ok",
            "fetched": len(raw_features),
            "valid": len(events),
            "new": new_count,
            "already_stored": len(events) - new_count,
        }

    except Exception as e:
        log.error("manual_sync_error", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error sincronizando con USGS: {str(e)}")
