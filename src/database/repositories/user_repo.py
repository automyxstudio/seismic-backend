"""
Repositorio para la colección 'users'.

Maneja la persistencia de usuarios para el sistema de autenticación.
Las contraseñas siempre llegan ya hasheadas — este repositorio
nunca recibe ni almacena texto plano.
"""

import structlog
from motor.motor_asyncio import AsyncIOMotorDatabase
from src.models.user import UserDocument

log = structlog.get_logger()


class UserRepository:
    """Operaciones de lectura y escritura sobre la colección users."""

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self.collection = db.users

    async def create(self, user: UserDocument) -> str:
        """
        Crea un nuevo usuario.

        Returns:
            ID del documento creado como string.
        """
        result = await self.collection.insert_one(user.model_dump())
        log.info("user_created", username=user.username)
        return str(result.inserted_id)

    async def find_by_username(self, username: str) -> dict | None:
        """
        Busca un usuario por username.
        Retorna None si no existe — el servicio de auth decide qué hacer.
        """
        doc = await self.collection.find_one({"username": username})
        if doc:
            doc["_id"] = str(doc["_id"])
        return doc

    async def exists(self, username: str) -> bool:
        """Verifica si un username ya está registrado. Usado para el seed inicial."""
        count = await self.collection.count_documents({"username": username}, limit=1)
        return count > 0
