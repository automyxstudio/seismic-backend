"""
Rutas de la capa analítica — Nivel 4.

Expone tres capacidades sobre los datos históricos sísmicos:

  GET /analytics/export
    Dispara la exportación de la última hora a Parquet y retorna metadata
    del archivo generado (ruta, filas, tamaño). Útil para testing manual.

  GET /analytics/ml-dataset
    Retorna un dataset con feature engineering listo para entrenar modelos ML.
    Lee desde los Parquets exportados (capa analítica) o cae back a MongoDB.
    Soporta ?days=N para controlar la ventana histórica y ?format=json|csv.

  GET /analytics/parquet-files
    Lista los archivos Parquet del data lake con metadata (filas, tamaño, fecha).
    Muestra la estructura de particionado year/month/day.

Separación de capas:
  MongoDB  → escrituras operacionales, queries en tiempo real
  Parquet  → datos históricos inmutables, análisis de tendencias, ML
"""

import io
import asyncio
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from src.api.dependencies import get_current_user
from src.services.analytics_service import AnalyticsService, PARQUET_BASE

log = structlog.get_logger()
router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/export")
async def export_to_parquet(
    hours_ago: int = Query(1, ge=1, le=168, description="Exportar datos de N horas atrás"),
    current_user: dict = Depends(get_current_user),
) -> dict:
    """
    Exporta una ventana horaria a Parquet en el data lake.

    El Airflow DAG llama a este mismo servicio cada hora automáticamente.
    Este endpoint permite disparar la exportación manualmente para demo o backfill.

    La ruta resultante sigue particionado Hive: year=YYYY/month=MM/day=DD/HH.parquet
    """
    now = datetime.now(timezone.utc)
    period_start = (now - timedelta(hours=hours_ago)).replace(
        minute=0, second=0, microsecond=0
    )

    # Ejecutar en thread pool — AnalyticsService usa pymongo sync
    loop = asyncio.get_event_loop()
    service = AnalyticsService()
    try:
        result = await loop.run_in_executor(
            None, service.export_hour_to_parquet, period_start
        )
    finally:
        service.close()

    return {
        "status": "ok",
        "period": period_start.isoformat(),
        "rows_exported": result["rows"],
        "parquet_path": result["path"],
        "size_kb": result.get("size_kb", 0),
        "message": "Sin datos para este período" if result["rows"] == 0 else "Exportación completada",
    }


@router.get("/ml-dataset")
async def get_ml_dataset(
    days: int = Query(7, ge=1, le=90, description="Ventana histórica en días"),
    format: str = Query("json", pattern="^(json|csv)$", description="Formato de salida"),
    current_user: dict = Depends(get_current_user),
):
    """
    Retorna un dataset con feature engineering para entrenamiento de modelos ML.

    Features incluidas:
    - magnitude: magnitud del sismo (variable objetivo para regresión)
    - magnitude_range_encoded: rango codificado 0-5 (para clasificación)
    - hour_of_day: hora UTC del evento (captura patrones temporales)
    - depth_category_encoded: 0=superficial, 1=intermedio, 2=profundo
    - lat_grid / lon_grid: celda 5°×5° (ubicación geoespacial discreta)
    - is_significant: 1 si magnitud ≥ 4.0 (variable binaria)

    Lee desde los archivos Parquet exportados (capa analítica) cuando existen.
    Si no hay Parquets aún, hace fallback a MongoDB directamente.
    """
    loop = asyncio.get_event_loop()
    service = AnalyticsService()
    try:
        df = await loop.run_in_executor(None, service.generate_ml_dataset, days)
    finally:
        service.close()

    if df.empty:
        return {
            "status": "ok",
            "rows": 0,
            "features": [],
            "data": [],
            "message": f"Sin datos en los últimos {days} días",
        }

    if format == "csv":
        buf = io.StringIO()
        df.to_csv(buf, index=False)
        buf.seek(0)
        return StreamingResponse(
            io.BytesIO(buf.getvalue().encode()),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=seismic_ml_{days}d.csv"},
        )

    return {
        "status": "ok",
        "days": days,
        "rows": len(df),
        "features": list(df.columns),
        "feature_descriptions": {
            "magnitude": "Magnitud del sismo — variable objetivo para regresión",
            "magnitude_range_encoded": "Rango ordinal 0=micro … 5=mayor — para clasificación",
            "hour_of_day": "Hora UTC del evento [0-23] — patrón temporal circadiano",
            "depth_category_encoded": "0=superficial(<70km) 1=intermedio 2=profundo(≥300km)",
            "lat_grid": "Celda latitud 5° — agregación geoespacial",
            "lon_grid": "Celda longitud 5° — agregación geoespacial",
            "is_significant": "1 si magnitud ≥ 4.0 — variable objetivo binaria",
        },
        "data": df.to_dict(orient="records"),
    }


@router.get("/parquet-files")
async def list_parquet_files(
    current_user: dict = Depends(get_current_user),
) -> dict:
    """
    Lista los archivos Parquet del data lake con metadata.

    Muestra la estructura de particionado year/month/day que permite
    a herramientas como Spark, DuckDB o Pandas leer solo las particiones
    necesarias sin escanear todo el dataset (partition pruning).
    """
    if not PARQUET_BASE.exists():
        return {
            "status": "ok",
            "total_files": 0,
            "total_size_kb": 0,
            "files": [],
            "message": "Data lake vacío — ejecuta GET /analytics/export para generar el primer Parquet",
        }

    files = []
    total_size = 0

    for path in sorted(PARQUET_BASE.rglob("*.parquet")):
        size_kb = path.stat().st_size // 1024
        total_size += size_kb
        # Extraer fecha de la ruta (year=YYYY/month=MM/day=DD/HH.parquet)
        parts = {p.split("=")[0]: p.split("=")[1] for p in path.parts if "=" in p}
        files.append({
            "path": str(path.relative_to(PARQUET_BASE)),
            "year": parts.get("year"),
            "month": parts.get("month"),
            "day": parts.get("day"),
            "hour": path.stem,
            "size_kb": size_kb,
        })

    return {
        "status": "ok",
        "total_files": len(files),
        "total_size_kb": total_size,
        "partition_scheme": "year=YYYY/month=MM/day=DD/HH.parquet",
        "files": files,
    }
