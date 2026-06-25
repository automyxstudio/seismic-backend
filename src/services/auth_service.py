"""
Servicio de autenticación JWT.

Centraliza la lógica de:
  - Hashing y verificación de contraseñas (bcrypt via passlib).
  - Creación de access tokens (vida corta: 15 min).
  - Creación de refresh tokens (vida larga: 7 días).
  - Verificación de refresh tokens para renovar el access token.

La separación entre access y refresh token se hace con el campo 'type'
en el payload del JWT. Un refresh token no puede usarse como access token
— se valida en la dependencia get_current_user.
"""

from datetime import datetime, timedelta, timezone
from jose import JWTError, jwt
from passlib.context import CryptContext
import structlog

from src.config.settings import get_settings

log = structlog.get_logger()

# Contexto de hashing — bcrypt con costo por defecto (12 rounds)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    """Hashea una contraseña en texto plano con bcrypt."""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verifica si una contraseña en texto plano coincide con el hash almacenado.
    Bcrypt maneja internamente la comparación segura (timing-safe).
    """
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(username: str) -> str:
    """
    Crea un JWT de acceso con vida corta.

    Payload: {sub: username, type: 'access', exp: <15 min desde ahora>}
    """
    settings = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.jwt_access_token_expire_minutes
    )
    payload = {"sub": username, "type": "access", "exp": expire}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_refresh_token(username: str) -> str:
    """
    Crea un JWT de refresco con vida larga.

    Payload: {sub: username, type: 'refresh', exp: <7 días desde ahora>}
    El campo 'type' impide que este token se use como access token.
    """
    settings = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(
        days=settings.jwt_refresh_token_expire_days
    )
    payload = {"sub": username, "type": "refresh", "exp": expire}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_refresh_token(token: str) -> str | None:
    """
    Valida un refresh token y retorna el username.

    Returns:
        Username si el token es válido y es de tipo 'refresh', None si no.
    """
    settings = get_settings()
    try:
        payload = jwt.decode(
            token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
        )
        if payload.get("type") != "refresh":
            return None
        return payload.get("sub")
    except JWTError:
        return None
