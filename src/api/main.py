"""
Aplicación FastAPI principal.

El lifespan gestiona el ciclo de vida completo:
  - Startup: conectar MongoDB y Redis, crear índices, crear usuario seed.
  - Shutdown: cerrar conexiones limpiamente.

Prometheus instrumenta automáticamente todos los endpoints con métricas
de latencia, requests por segundo y errores por código HTTP.
"""

import structlog
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator

from src.config.settings import get_settings
from src.config.logging import setup_logging
from src.database.mongodb import connect_to_mongo, close_mongo_connection, get_database
from src.database.redis import connect_to_redis, close_redis_connection
from src.database.indexes import create_indexes
from src.database.repositories.user_repo import UserRepository
from src.services.auth_service import hash_password
from src.models.user import UserDocument
from src.api.routes import auth, earthquakes, metrics, reports, ws

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Gestiona el ciclo de vida de la app.

    Todo lo que está antes del 'yield' se ejecuta al arrancar.
    Todo lo que está después del 'yield' se ejecuta al apagar.
    """
    settings = get_settings()
    setup_logging(settings.api_env)

    log.info("api_starting", env=settings.api_env)

    # Conectar bases de datos
    await connect_to_mongo()
    await connect_to_redis()

    db = get_database()

    # Crear índices (idempotente)
    await create_indexes(db)

    # Crear usuario seed si no existe
    await _seed_admin_user(db, settings)

    log.info("api_ready")

    yield  # La app está corriendo aquí

    # Shutdown — cerrar conexiones limpiamente
    log.info("api_shutting_down")
    await close_mongo_connection()
    await close_redis_connection()


async def _seed_admin_user(db, settings) -> None:
    """
    Crea el usuario admin inicial si no existe.

    Las credenciales vienen de variables de entorno — nunca hardcodeadas.
    Permite que el sistema sea usable desde el primer `docker compose up`.
    """
    repo = UserRepository(db)
    exists = await repo.exists(settings.seed_username)

    if not exists:
        user = UserDocument(
            username=settings.seed_username,
            email=settings.seed_email,
            hashed_password=hash_password(settings.seed_password),
        )
        await repo.create(user)
        log.info("seed_user_created", username=settings.seed_username)


def create_app() -> FastAPI:
    """
    Factory de la aplicación FastAPI.

    Usar factory pattern permite crear instancias distintas para tests
    sin modificar el módulo global.
    """
    settings = get_settings()

    app = FastAPI(
        title="Seismic Platform API",
        description="Plataforma de monitoreo de eventos sísmicos en tiempo real",
        version="1.0.0",
        lifespan=lifespan,
    )

    # CORS — permite peticiones desde el frontend Angular
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:4200"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Prometheus — instrumenta todos los endpoints automáticamente
    Instrumentator().instrument(app).expose(app)

    # Registrar rutas
    app.include_router(auth.router)
    app.include_router(earthquakes.router)
    app.include_router(metrics.router)
    app.include_router(reports.router)
    app.include_router(ws.router)

    @app.get("/health", tags=["health"])
    async def health() -> dict:
        """Endpoint de salud usado por el healthcheck del docker-compose."""
        return {"status": "ok"}

    return app


# Instancia de la app — referenciada por uvicorn: src.api.main:app
app = create_app()
