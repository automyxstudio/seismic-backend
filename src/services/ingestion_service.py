"""
Servicio de ingesta de eventos sísmicos.

Orquesta el ciclo completo cada N segundos (default: 180 = 3 min):
  1. Fetch → consulta la API de USGS.
  2. Transform → convierte el GeoJSON a modelos internos.
  3. Upsert → persiste solo los eventos nuevos (deduplicación).
  4. Metrics → actualiza métricas y notifica al WebSocket vía Redis.

Este servicio corre como proceso independiente en el contenedor 'ingesta'
del docker-compose. No es parte de FastAPI.

El loop es resiliente: un error en un ciclo no detiene el servicio —
se loguea y se espera al siguiente intervalo.
"""

import asyncio
import structlog

from src.clients.usgs_client import USGSClient
from src.services.processing_service import ProcessingService
from src.services.metrics_service import MetricsService
from src.database.repositories.earthquake_repo import EarthquakeRepository
from src.database.mongodb import connect_to_mongo, get_database
from src.database.redis import connect_to_redis, get_redis
from src.database.indexes import create_indexes
from src.config.settings import get_settings
from src.config.logging import setup_logging

log = structlog.get_logger()


class IngestionService:
    """
    Loop principal de ingesta. Corre indefinidamente en el contenedor de ingesta.

    Diseñado para ser instanciado una vez y ejecutar run() que no retorna.
    """

    def __init__(
        self,
        usgs_client: USGSClient,
        processing_service: ProcessingService,
        earthquake_repo: EarthquakeRepository,
        metrics_service: MetricsService,
        interval_seconds: int,
    ) -> None:
        self.usgs_client = usgs_client
        self.processing = processing_service
        self.earthquake_repo = earthquake_repo
        self.metrics = metrics_service
        self.interval = interval_seconds

    async def run(self) -> None:
        """
        Loop principal. Ejecuta un ciclo de ingesta y espera interval_seconds.

        No lanza excepciones al exterior — los errores se logean y el loop continúa.
        """
        log.info("ingestion_service_started", interval_seconds=self.interval)

        while True:
            await self._run_cycle()
            await asyncio.sleep(self.interval)

    async def _run_cycle(self) -> None:
        """
        Un ciclo completo de ingesta: fetch → transform → upsert → metrics.

        Los errores se capturan aquí para que el loop en run() nunca se detenga.
        """
        try:
            # 1. Fetch — obtener features crudos de USGS
            raw_features = await self.usgs_client.fetch_earthquakes()

            if not raw_features:
                log.info("ingestion_cycle_empty", message="No hay sismos en la ultima hora")
                return

            # 2. Transform — convertir a modelo interno, descartar inválidos
            events = self.processing.transform_many(raw_features)

            # 3. Upsert + 4. Metrics — solo para eventos que no existían
            new_count = 0
            for event in events:
                is_new = await self.earthquake_repo.upsert(event)
                if is_new:
                    await self.metrics.process_new_event(event)
                    new_count += 1

            log.info(
                "ingestion_cycle_done",
                total_fetched=len(raw_features),
                valid=len(events),
                new_inserted=new_count,
            )

        except Exception as e:
            # Captura cualquier error para que el loop no muera
            log.error("ingestion_cycle_error", error=str(e), exc_info=True)


async def main() -> None:
    """
    Punto de entrada del proceso de ingesta.

    Inicializa conexiones, crea índices y arranca el loop.
    Se ejecuta con: python -m src.services.ingestion_service
    """
    settings = get_settings()
    setup_logging(settings.api_env)

    log.info("ingestion_process_starting")

    # Conectar a bases de datos
    await connect_to_mongo()
    await connect_to_redis()

    db = get_database()
    redis = get_redis()

    # Crear índices si no existen (idempotente)
    await create_indexes(db)

    # Construir el grafo de dependencias
    service = IngestionService(
        usgs_client=USGSClient(),
        processing_service=ProcessingService(),
        earthquake_repo=EarthquakeRepository(db),
        metrics_service=MetricsService(db=db, redis=redis),
        interval_seconds=settings.ingestion_interval_seconds,
    )

    await service.run()


if __name__ == "__main__":
    asyncio.run(main())
