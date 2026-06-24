"""
Modelos Pydantic para eventos sísmicos.

Se usan dos modelos separados por responsabilidad:
- EarthquakeDocument: define la estructura exacta del documento en MongoDB.
- EarthquakeResponse: define lo que expone la API (convierte _id de ObjectId a str).

Esta separación (SOLID-S) permite cambiar el esquema interno sin afectar
el contrato de la API, y viceversa.
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
from src.config.constants import MagnitudeRange


class EarthquakeDocument(BaseModel):
    """Documento tal como se almacena en MongoDB earthquakes."""

    event_id: str
    """ID único del evento provisto por USGS. Usado para deduplicación."""

    magnitude: float
    """Magnitud del sismo en la escala de Richter."""

    magnitude_range: MagnitudeRange
    """Categoría calculada en la ingesta. Almacenada para queries eficientes."""

    location: str
    """Descripción textual de la ubicación (e.g. '20 km NW of California')."""

    latitude: float
    longitude: float
    depth: float
    """Profundidad del hipocentro en kilómetros."""

    event_time: datetime
    """Timestamp del evento según USGS (convertido de milisegundos Unix)."""

    ingested_at: datetime = Field(default_factory=datetime.utcnow)
    """Timestamp de cuando el sistema procesó el evento."""


class EarthquakeResponse(BaseModel):
    """Representación del evento para la API REST."""

    id: Optional[str] = Field(None, alias="_id")
    event_id: str
    magnitude: float
    magnitude_range: MagnitudeRange
    location: str
    latitude: float
    longitude: float
    depth: float
    event_time: datetime
    ingested_at: datetime

    model_config = {"populate_by_name": True}


class EarthquakeListResponse(BaseModel):
    """Respuesta paginada para GET /earthquakes."""

    total: int
    """Total de documentos que coinciden con los filtros aplicados."""

    page: int
    page_size: int
    items: list[EarthquakeResponse]
