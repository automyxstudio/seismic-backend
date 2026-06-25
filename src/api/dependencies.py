"""
Dependencias compartidas de FastAPI.

Centraliza la lógica de inyección de dependencias para que los routers
no necesiten saber cómo obtener la base de datos, Redis o el usuario actual.

FastAPI resuelve estas dependencias automáticamente en cada request.
"""

import structlog
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from motor.motor_asyncio import AsyncIOMotorDatabase
import redis.asyncio as aioredis

from src.database.mongodb import get_database
from src.database.redis import get_redis
from src.database.repositories.user_repo import UserRepository
from src.models.user import TokenPayload
from src.config.settings import get_settings

log = structlog.get_logger()

# FastAPI extrae el token del header Authorization: Bearer <token>
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> dict:
    """
    Dependencia que valida el JWT y retorna el usuario autenticado.

    Se inyecta en cualquier endpoint que requiera autenticación:
        current_user = Depends(get_current_user)

    Raises:
        HTTPException 401: si el token es inválido, expirado o el usuario no existe.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token inválido o expirado",
        headers={"WWW-Authenticate": "Bearer"},
    )

    settings = get_settings()

    try:
        payload_data = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        payload = TokenPayload(**payload_data)

        # Rechazar explícitamente refresh tokens usados como access tokens
        if payload.type != "access":
            raise credentials_exception

        username = payload.sub

    except JWTError:
        raise credentials_exception

    repo = UserRepository(db)
    user = await repo.find_by_username(username)

    if not user or not user.get("is_active", False):
        raise credentials_exception

    return user
