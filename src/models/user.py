"""
Modelos Pydantic para usuarios y autenticación JWT.

La separación entre UserDocument y UserResponse es crítica por seguridad:
UserResponse nunca expone el hash de la contraseña, sin importar cómo
se llame al endpoint. Es una protección por diseño, no por convención.

TokenResponse y TokenPayload definen el contrato del sistema JWT:
- access_token: vida corta (15 min), se usa en cada request.
- refresh_token: vida larga (7 días), solo se usa para renovar el access token.
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, EmailStr


class UserDocument(BaseModel):
    """Usuario almacenado en MongoDB. Incluye el hash de contraseña."""

    username: str
    email: EmailStr
    hashed_password: str
    """Contraseña hasheada con bcrypt. Nunca se almacena en texto plano."""

    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)


class UserResponse(BaseModel):
    """
    Representación pública del usuario para la API.
    No incluye hashed_password — protección por diseño.
    """

    id: Optional[str] = Field(None, alias="_id")
    username: str
    email: EmailStr
    is_active: bool
    created_at: datetime

    model_config = {"populate_by_name": True}


class TokenResponse(BaseModel):
    """Respuesta del endpoint POST /auth/login y POST /auth/refresh."""

    access_token: str
    """JWT de corta duración (15 min) para autenticar requests a la API."""

    refresh_token: str
    """JWT de larga duración (7 días) para obtener nuevos access tokens."""

    token_type: str = "bearer"


class TokenPayload(BaseModel):
    """Payload decodificado de un JWT. Se valida en cada request autenticado."""

    sub: str
    """Subject: username del usuario propietario del token."""

    exp: int
    """Expiration: timestamp Unix de expiración."""

    type: str
    """Tipo de token: 'access' o 'refresh'. Evita usar un refresh como access."""
