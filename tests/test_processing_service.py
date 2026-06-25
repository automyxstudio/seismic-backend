"""
Tests unitarios para ProcessingService.transform() y transform_many().

Cubren:
  - Transformación exitosa de un feature GeoJSON válido.
  - Mapeo correcto de cada campo (event_id, magnitude, location, coords, timestamp).
  - Conversión de timestamp de milisegundos Unix a datetime UTC.
  - Descarte de eventos sin magnitud (mag=None).
  - Descarte de eventos con estructura inválida (campos faltantes).
  - transform_many: mezcla de válidos e inválidos → retorna solo los válidos.
"""

import pytest
from datetime import timezone
from src.services.processing_service import ProcessingService
from src.config.constants import MagnitudeRange


@pytest.fixture
def service():
    return ProcessingService()


class TestTransform:
    """Tests para ProcessingService.transform()."""

    def test_transforma_feature_valido(self, service, raw_feature_factory):
        """Un feature bien formado produce un EarthquakeDocument completo."""
        feature = raw_feature_factory(
            event_id="us7000abc1",
            magnitude=4.5,
            place="15km NW of Test City",
            time_ms=1_750_000_000_000,
            longitude=-118.5,
            latitude=34.2,
            depth=12.3,
        )
        result = service.transform(feature)

        assert result is not None
        assert result.event_id == "us7000abc1"
        assert result.magnitude == 4.5
        assert result.magnitude_range == MagnitudeRange.LIGERO
        assert result.location == "15km NW of Test City"
        assert result.longitude == -118.5
        assert result.latitude == 34.2
        assert result.depth == 12.3

    def test_convierte_timestamp_milisegundos_a_utc(self, service, raw_feature_factory):
        """USGS entrega el tiempo en ms Unix — debe convertirse a datetime con tz=UTC."""
        # 1_750_000_000_000 ms = 1_750_000_000 s = 2025-06-15T16:53:20Z
        feature = raw_feature_factory(time_ms=1_750_000_000_000)
        result = service.transform(feature)

        assert result is not None
        assert result.event_time.tzinfo == timezone.utc
        assert result.event_time.timestamp() == pytest.approx(1_750_000_000.0, abs=1)

    def test_descarta_evento_sin_magnitud(self, service, raw_feature_factory):
        """mag=None → retorna None (evento en proceso de análisis en USGS)."""
        feature = raw_feature_factory(magnitude=None)
        feature["properties"]["mag"] = None

        result = service.transform(feature)
        assert result is None

    def test_descarta_evento_sin_geometria(self, service, raw_feature_factory):
        """Geometría ausente → retorna None (KeyError manejado internamente)."""
        feature = raw_feature_factory()
        del feature["geometry"]

        result = service.transform(feature)
        assert result is None

    def test_descarta_evento_sin_properties(self, service, raw_feature_factory):
        """Properties ausentes → retorna None."""
        feature = raw_feature_factory()
        del feature["properties"]

        result = service.transform(feature)
        assert result is None

    def test_descarta_evento_sin_time(self, service, raw_feature_factory):
        """Campo 'time' ausente → retorna None (no se puede construir el datetime)."""
        feature = raw_feature_factory()
        del feature["properties"]["time"]

        result = service.transform(feature)
        assert result is None

    def test_location_desconocida_cuando_place_ausente(self, service, raw_feature_factory):
        """Si 'place' no está en properties, location queda como 'Unknown'."""
        feature = raw_feature_factory()
        del feature["properties"]["place"]

        result = service.transform(feature)
        assert result is not None
        assert result.location == "Unknown"

    def test_clasifica_magnitud_correctamente(self, service, raw_feature_factory):
        """La magnitud_range se calcula en transform, no se recibe del exterior."""
        casos = [
            (1.0, MagnitudeRange.MICRO),
            (2.5, MagnitudeRange.MENOR),
            (4.2, MagnitudeRange.LIGERO),
            (5.8, MagnitudeRange.MODERADO),
            (6.3, MagnitudeRange.FUERTE),
            (7.1, MagnitudeRange.MAYOR),
        ]
        for mag, expected_range in casos:
            feature = raw_feature_factory(magnitude=mag)
            result = service.transform(feature)
            assert result is not None
            assert result.magnitude_range == expected_range, f"Fallo para magnitud {mag}"

    def test_magnitud_se_convierte_a_float(self, service, raw_feature_factory):
        """USGS puede entregar la magnitud como int — se convierte a float."""
        feature = raw_feature_factory()
        feature["properties"]["mag"] = 5  # entero, no float

        result = service.transform(feature)
        assert result is not None
        assert isinstance(result.magnitude, float)
        assert result.magnitude == 5.0


class TestTransformMany:
    """Tests para ProcessingService.transform_many()."""

    def test_transforma_lista_completa_valida(self, service, raw_feature_factory):
        """Lista de features válidos → todos transformados."""
        features = [raw_feature_factory(event_id=f"ev{i}") for i in range(5)]
        results = service.transform_many(features)

        assert len(results) == 5

    def test_descarta_invalidos_en_lista_mixta(self, service, raw_feature_factory):
        """Lista con válidos e inválidos → solo retorna los válidos."""
        valido1 = raw_feature_factory(event_id="ev001")
        valido2 = raw_feature_factory(event_id="ev002")
        invalido = raw_feature_factory()
        invalido["properties"]["mag"] = None  # sin magnitud → descartado

        results = service.transform_many([valido1, invalido, valido2])

        assert len(results) == 2
        ids = [r.event_id for r in results]
        assert "ev001" in ids
        assert "ev002" in ids

    def test_lista_vacia(self, service):
        """Lista vacía → lista vacía (sin errores)."""
        results = service.transform_many([])
        assert results == []

    def test_todos_invalidos(self, service, raw_feature_factory):
        """Todos los features inválidos → lista vacía."""
        features = [raw_feature_factory() for _ in range(3)]
        for f in features:
            f["properties"]["mag"] = None

        results = service.transform_many(features)
        assert results == []
