"""
Servicio de transformación y validación de eventos sísmicos.

Convierte el formato crudo de USGS (GeoJSON) al modelo interno EarthquakeDocument.
Es la única capa que conoce la estructura exacta del JSON de USGS.

Responsabilidades:
  - Extraer campos del GeoJSON (properties + geometry).
  - Convertir el timestamp de milisegundos Unix a datetime.
  - Clasificar la magnitud con classify_magnitude().
  - Descartar eventos sin magnitud (USGS a veces retorna mag=None).
"""

from datetime import datetime, timezone
from typing import Optional
import structlog

from src.models.earthquake import EarthquakeDocument
from src.config.constants import classify_magnitude, MagnitudeRange

log = structlog.get_logger()


class ProcessingService:
    """Transforma features crudos de USGS a documentos internos."""

    def transform(self, raw_feature: dict) -> Optional[EarthquakeDocument]:
        """
        Convierte un feature GeoJSON de USGS a EarthquakeDocument.

        Args:
            raw_feature: dict con estructura GeoJSON de USGS.

        Returns:
            EarthquakeDocument listo para persistir, o None si el evento
            no tiene los datos mínimos necesarios (e.g. magnitud nula).
        """
        try:
            props = raw_feature["properties"]
            coords = raw_feature["geometry"]["coordinates"]
            event_id = raw_feature["id"]

            magnitude = props.get("mag")
            if magnitude is None:
                log.warning("event_skipped_no_magnitude", event_id=event_id)
                return None

            # USGS entrega el tiempo en milisegundos Unix — convertir a datetime UTC
            time_ms = props["time"]
            event_time = datetime.fromtimestamp(time_ms / 1000, tz=timezone.utc)

            return EarthquakeDocument(
                event_id=event_id,
                magnitude=float(magnitude),
                magnitude_range=classify_magnitude(float(magnitude)),
                location=props.get("place", "Unknown"),
                longitude=coords[0],
                latitude=coords[1],
                depth=coords[2],
                event_time=event_time,
            )

        except (KeyError, IndexError, TypeError, ValueError) as e:
            log.error(
                "event_transform_error",
                event_id=raw_feature.get("id", "unknown"),
                error=str(e),
            )
            return None

    def transform_many(self, raw_features: list[dict]) -> list[EarthquakeDocument]:
        """
        Transforma una lista de features, descartando los inválidos.

        Returns:
            Lista de EarthquakeDocument válidos. Puede ser más corta que la entrada.
        """
        results = [self.transform(f) for f in raw_features]
        valid = [r for r in results if r is not None]

        if len(valid) < len(raw_features):
            log.warning(
                "events_skipped",
                total=len(raw_features),
                valid=len(valid),
                skipped=len(raw_features) - len(valid),
            )

        return valid
