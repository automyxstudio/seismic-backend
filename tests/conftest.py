"""
Fixtures compartidas para toda la suite de tests.

Provee:
  - raw_feature_factory: crea features GeoJSON de USGS con valores controlados.
  - settings_override: inyecta variables de entorno de test sin tocar el .env real.
"""

import os
import pytest


@pytest.fixture(autouse=True)
def settings_override(monkeypatch):
    """
    Inyecta variables de entorno mínimas para que Settings() arranque en tests.
    Se aplica a TODOS los tests del proyecto (autouse=True).
    """
    monkeypatch.setenv("MONGO_URI", "mongodb://localhost:27017/test_db")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/1")
    monkeypatch.setenv("JWT_SECRET_KEY", "test_secret_key_32_chars_minimum_ok")
    monkeypatch.setenv("JWT_ALGORITHM", "HS256")
    monkeypatch.setenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "15")
    monkeypatch.setenv("JWT_REFRESH_TOKEN_EXPIRE_DAYS", "7")
    monkeypatch.setenv("SEED_USERNAME", "admin")
    monkeypatch.setenv("SEED_PASSWORD", "admin123")
    monkeypatch.setenv("SEED_EMAIL", "admin@example.com")
    # Limpiar caché del singleton para que tome los nuevos valores
    from src.config.settings import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def raw_feature_factory():
    """
    Factory que construye features GeoJSON válidos con valores parametrizables.

    Uso:
        feature = raw_feature_factory(event_id="us123", magnitude=5.5)
    """
    def _make(
        event_id: str = "us7000test1",
        magnitude: float = 3.5,
        place: str = "10km NE of Test City",
        time_ms: int = 1_750_000_000_000,  # timestamp fijo: 2025-06-14T22:06:40Z
        longitude: float = -118.0,
        latitude: float = 34.0,
        depth: float = 10.0,
    ) -> dict:
        return {
            "id": event_id,
            "properties": {
                "mag": magnitude,
                "place": place,
                "time": time_ms,
            },
            "geometry": {
                "type": "Point",
                "coordinates": [longitude, latitude, depth],
            },
        }
    return _make
