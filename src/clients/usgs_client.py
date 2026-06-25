"""
Cliente HTTP para la API pública de USGS Earthquake Program.

Responsabilidad única: obtener los datos crudos de USGS y retornarlos.
No transforma, no valida el modelo interno, no sabe nada de MongoDB.

Si la API de USGS cambia su estructura o URL, solo se toca este archivo.
"""

import httpx
import structlog
from src.config.settings import get_settings

log = structlog.get_logger()


class USGSClient:
    """Cliente async para el feed GeoJSON de la API de USGS."""

    def __init__(self) -> None:
        self.url = get_settings().usgs_api_url
        # Timeout generoso — la API pública puede ser lenta
        self._timeout = httpx.Timeout(30.0, connect=10.0)

    async def fetch_earthquakes(self) -> list[dict]:
        """
        Consulta el feed de la última hora y retorna la lista de features crudos.

        Cada feature es un dict con la estructura GeoJSON de USGS:
        {
            "id": "us7000xxxx",
            "properties": {"mag": 4.2, "place": "...", "time": 1718610000000},
            "geometry": {"coordinates": [-120.12, 35.44, 10.5]}
        }

        Returns:
            Lista de features. Lista vacía si no hay sismos en la última hora.

        Raises:
            httpx.HTTPError: si la API retorna un error HTTP.
            httpx.TimeoutException: si la API no responde en 30 segundos.
        """
        log.info("usgs_fetch_start", url=self.url)

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.get(self.url)
            response.raise_for_status()
            data = response.json()

        features = data.get("features", [])
        log.info("usgs_fetch_done", total_features=len(features))
        return features
