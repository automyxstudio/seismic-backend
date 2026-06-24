"""
Modelos Pydantic para métricas sísmicas por ventana horaria.

Se mantiene un documento por hora en la colección 'metrics'.
Cada vez que llega un evento nuevo, se actualiza el documento
de la ventana horaria correspondiente (upsert atómico en MongoDB).
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class MagnitudeDistribution(BaseModel):
    """Conteo de eventos por rango de magnitud dentro de una ventana horaria."""

    micro: int = 0
    menor: int = 0
    ligero: int = 0
    moderado: int = 0
    fuerte: int = 0
    mayor: int = 0


class MetricDocument(BaseModel):
    """
    Métricas agregadas por ventana horaria. Una doc por hora en MongoDB.

    El campo 'window' actúa como clave natural (e.g. '2026-06-17T10').
    Se usa upsert con $inc y $max para actualizar de forma atómica
    sin necesidad de leer el documento antes de escribir.
    """

    window: str
    """Ventana horaria en formato 'YYYY-MM-DDTHH'. Clave única del documento."""

    earthquake_count: int = 0
    avg_magnitude: float = 0.0
    max_magnitude: float = 0.0
    magnitude_distribution: MagnitudeDistribution = Field(
        default_factory=MagnitudeDistribution
    )
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class MetricResponse(BaseModel):
    """Representación de métricas para la API REST."""

    id: Optional[str] = Field(None, alias="_id")
    window: str
    earthquake_count: int
    avg_magnitude: float
    max_magnitude: float
    magnitude_distribution: MagnitudeDistribution
    updated_at: datetime

    model_config = {"populate_by_name": True}
