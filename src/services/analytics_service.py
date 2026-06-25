"""
Servicio de capa analítica — separación entre datos transaccionales y analíticos.

Arquitectura de dos capas:
  Transaccional → MongoDB (escrituras frecuentes, queries operacionales)
  Analítica     → Parquet en /data/parquet/ (columnar, optimizado para ML y análisis)

El servicio exporta eventos sísmicos desde MongoDB a archivos Parquet particionados
por fecha (year=YYYY/month=MM/day=DD). Airflow llama a este servicio cada hora.

Los archivos Parquet son la fuente de verdad para:
  - Análisis histórico de tendencias
  - Generación de datasets de entrenamiento para ML
  - Consultas analíticas de gran volumen sin impactar MongoDB

Feature engineering para ML (generate_ml_dataset):
  - magnitude_range_encoded: ordinal del rango (0=micro, 5=mayor)
  - hour_of_day: hora UTC del evento (patrón circadiano de sismos)
  - depth_category: shallow/intermediate/deep (clasificación geofísica)
  - lat_lon_grid: celda de 5° × 5° para análisis geoespacial agregado
"""

import os
import structlog
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from pymongo import MongoClient

from src.config.settings import get_settings

log = structlog.get_logger()

# Directorio base del data lake — montado como volumen en Docker
PARQUET_BASE = Path(os.getenv("PARQUET_DATA_DIR", "/data/parquet"))

# Codificación ordinal de rangos de magnitud para ML
RANGE_ENCODING = {
    "micro": 0,
    "menor": 1,
    "ligero": 2,
    "moderado": 3,
    "fuerte": 4,
    "mayor": 5,
}

# Schema Parquet explícito — garantiza consistencia entre particiones
EARTHQUAKE_SCHEMA = pa.schema([
    ("event_id", pa.string()),
    ("magnitude", pa.float64()),
    ("magnitude_range", pa.string()),
    ("location", pa.string()),
    ("latitude", pa.float64()),
    ("longitude", pa.float64()),
    ("depth", pa.float64()),
    ("event_time", pa.timestamp("ms", tz="UTC")),
    # Features derivadas
    ("magnitude_range_encoded", pa.int8()),
    ("hour_of_day", pa.int8()),
    ("depth_category", pa.string()),
    ("lat_grid", pa.int16()),
    ("lon_grid", pa.int16()),
])


class AnalyticsService:
    """
    Exporta datos sísmicos a Parquet y genera datasets para ML.

    Usa pymongo (sync) porque se llama desde Airflow (contexto síncrono).
    Para la API REST async se expone una versión que llama a este servicio
    en un executor de threads.
    """

    def __init__(self) -> None:
        settings = get_settings()
        self.client = MongoClient(settings.mongodb_url)
        self.db = self.client[settings.mongodb_db]

    def close(self) -> None:
        self.client.close()

    # ------------------------------------------------------------------ #
    #  Exportación a Parquet                                               #
    # ------------------------------------------------------------------ #

    def export_hour_to_parquet(self, period_start: datetime) -> dict:
        """
        Exporta los eventos de una ventana horaria a Parquet particionado.

        La partición sigue el esquema Hive: year=YYYY/month=MM/day=DD/HH.parquet
        Esto permite a herramientas como Spark, DuckDB o Pandas leer solo las
        particiones necesarias sin escanear todo el dataset.

        Args:
            period_start: inicio de la hora a exportar (UTC).

        Returns:
            dict con ruta del archivo, cantidad de filas y tamaño en bytes.
        """
        period_end = period_start + timedelta(hours=1)

        cursor = self.db.earthquakes.find(
            {
                "event_time": {
                    "$gte": period_start,
                    "$lt": period_end,
                }
            },
            {"_id": 0},
        )
        docs = list(cursor)

        if not docs:
            log.info("parquet_export_empty", period=period_start.isoformat())
            return {"rows": 0, "path": None}

        df = self._to_dataframe(docs)
        path = self._parquet_path(period_start)
        path.parent.mkdir(parents=True, exist_ok=True)

        table = pa.Table.from_pandas(df, schema=EARTHQUAKE_SCHEMA, preserve_index=False)
        pq.write_table(table, path, compression="snappy")

        size_kb = path.stat().st_size // 1024
        log.info("parquet_exported", path=str(path), rows=len(df), size_kb=size_kb)
        return {"rows": len(df), "path": str(path), "size_kb": size_kb}

    def generate_ml_dataset(self, days: int = 7) -> pd.DataFrame:
        """
        Genera un dataset con feature engineering para entrenamiento de modelos ML.

        Lee desde los Parquet ya exportados (capa analítica), no desde MongoDB,
        para demostrar la separación de capas.

        Si no hay Parquets todavía, cae back a MongoDB directamente.

        Features:
          - magnitude               → variable objetivo (regresión)
          - magnitude_range_encoded → variable objetivo (clasificación)
          - hour_of_day             → patrón temporal
          - depth_category_encoded  → 0=shallow, 1=intermediate, 2=deep
          - lat_grid, lon_grid      → ubicación geoespacial discreta

        Args:
            days: ventana histórica en días.

        Returns:
            DataFrame listo para entrenar un modelo.
        """
        since = datetime.now(timezone.utc) - timedelta(days=days)

        parquet_files = sorted(PARQUET_BASE.rglob("*.parquet")) if PARQUET_BASE.exists() else []

        if parquet_files:
            df = pd.read_parquet(PARQUET_BASE, engine="pyarrow")
            df = df[df["event_time"] >= pd.Timestamp(since, tz="UTC")]
            log.info("ml_dataset_from_parquet", files=len(parquet_files), rows=len(df))
        else:
            # Fallback: leer desde MongoDB si aún no hay Parquets exportados
            cursor = self.db.earthquakes.find(
                {"event_time": {"$gte": since}},
                {"_id": 0},
            )
            docs = list(cursor)
            df = self._to_dataframe(docs) if docs else pd.DataFrame()
            log.info("ml_dataset_from_mongo", rows=len(df))

        if df.empty:
            return df

        # Feature engineering adicional para ML
        df["depth_category_encoded"] = df["depth_category"].map(
            {"shallow": 0, "intermediate": 1, "deep": 2}
        )
        df["is_significant"] = (df["magnitude"] >= 4.0).astype(int)

        ml_columns = [
            "event_id", "magnitude", "magnitude_range_encoded",
            "hour_of_day", "depth_category_encoded",
            "lat_grid", "lon_grid", "is_significant",
        ]
        return df[[c for c in ml_columns if c in df.columns]]

    # ------------------------------------------------------------------ #
    #  Helpers internos                                                    #
    # ------------------------------------------------------------------ #

    def _to_dataframe(self, docs: list[dict]) -> pd.DataFrame:
        """Convierte documentos MongoDB a DataFrame con features derivadas."""
        df = pd.DataFrame(docs)

        # Normalizar event_time a timestamp UTC con ms precision
        df["event_time"] = pd.to_datetime(df["event_time"], utc=True).dt.floor("ms")

        # Feature: hora del día (patrón circadiano)
        df["hour_of_day"] = df["event_time"].dt.hour.astype("int8")

        # Feature: codificación ordinal del rango de magnitud
        df["magnitude_range_encoded"] = (
            df["magnitude_range"].map(RANGE_ENCODING).fillna(0).astype("int8")
        )

        # Feature: categoría de profundidad (clasificación geofísica estándar)
        df["depth_category"] = df["depth"].apply(_classify_depth)

        # Feature: celda de 5° × 5° para análisis geoespacial agregado
        df["lat_grid"] = (df["latitude"] // 5 * 5).astype("int16")
        df["lon_grid"] = (df["longitude"] // 5 * 5).astype("int16")

        # Garantizar tipos correctos para el schema Parquet
        df["magnitude"] = df["magnitude"].astype("float64")
        df["latitude"] = df["latitude"].astype("float64")
        df["longitude"] = df["longitude"].astype("float64")
        df["depth"] = df["depth"].astype("float64")

        return df[list(EARTHQUAKE_SCHEMA.names)]

    def _parquet_path(self, dt: datetime) -> Path:
        """
        Construye la ruta particionada tipo Hive para un timestamp dado.

        Ejemplo: /data/parquet/year=2026/month=06/day=24/14.parquet
        """
        return (
            PARQUET_BASE
            / f"year={dt.year}"
            / f"month={dt.month:02d}"
            / f"day={dt.day:02d}"
            / f"{dt.hour:02d}.parquet"
        )


def _classify_depth(depth: float) -> str:
    """Clasifica la profundidad según la escala geofísica estándar."""
    if depth < 70:
        return "shallow"
    if depth < 300:
        return "intermediate"
    return "deep"
