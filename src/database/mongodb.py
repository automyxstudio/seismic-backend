"""
Gestión del ciclo de vida de la conexión a MongoDB.

Usa Motor, el driver async oficial de MongoDB para Python.
La conexión se crea una sola vez en el startup de FastAPI (lifespan)
y se cierra al apagar — no se abre y cierra en cada request.

Motor internamente usa un connection pool, por lo que múltiples
coroutines comparten la misma conexión de forma segura y eficiente.
"""

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from src.config.settings import get_settings

_client: AsyncIOMotorClient | None = None


async def connect_to_mongo() -> None:
    """
    Abre la conexión a MongoDB. Llamar en el startup de la app.

    Motor no valida la conexión al crear el cliente — el primer
    comando real confirma que el servidor está disponible.
    """
    global _client
    settings = get_settings()
    _client = AsyncIOMotorClient(settings.mongo_uri)
    # Ping para verificar conectividad al arrancar
    await _client.admin.command("ping")


async def close_mongo_connection() -> None:
    """Cierra la conexión a MongoDB. Llamar en el shutdown de la app."""
    global _client
    if _client:
        _client.close()
        _client = None


def get_database() -> AsyncIOMotorDatabase:
    """
    Devuelve la instancia de la base de datos.
    Se usa como dependencia de FastAPI: Depends(get_database).
    """
    if _client is None:
        raise RuntimeError("MongoDB no está conectado. Llamar connect_to_mongo() primero.")
    settings = get_settings()
    return _client[settings.mongo_db]
