"""
Rutas de autenticación JWT.

Endpoints:
  POST /auth/login   — recibe username/password, retorna access + refresh token.
  POST /auth/refresh — recibe refresh token, retorna nuevo access token.
  GET  /auth/me      — retorna el usuario autenticado actual.
"""

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from src.database.mongodb import get_database
from src.database.repositories.user_repo import UserRepository
from src.models.user import TokenResponse, UserResponse
from src.services.auth_service import (
    verify_password,
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
)
from src.api.dependencies import get_current_user

log = structlog.get_logger()
router = APIRouter(prefix="/auth", tags=["auth"])


class RefreshRequest(BaseModel):
    """Body del endpoint POST /auth/refresh."""
    refresh_token: str


@router.post("/login", response_model=TokenResponse)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> TokenResponse:
    """
    Autentica al usuario y retorna el par de tokens JWT.

    Usa OAuth2PasswordRequestForm para compatibilidad con el esquema
    estándar de FastAPI — permite probar directamente desde /docs.
    """
    repo = UserRepository(db)
    user = await repo.find_by_username(form_data.username)

    if not user or not verify_password(form_data.password, user["hashed_password"]):
        log.warning("login_failed", username=form_data.username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales incorrectas",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(user["username"])
    refresh_token = create_refresh_token(user["username"])

    log.info("login_success", username=user["username"])

    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    body: RefreshRequest,
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> TokenResponse:
    """
    Renueva el access token usando un refresh token válido.

    El Angular lo llama automáticamente cuando recibe un 401 —
    el usuario nunca ve el error.
    """
    username = decode_refresh_token(body.refresh_token)

    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token inválido o expirado",
        )

    repo = UserRepository(db)
    user = await repo.find_by_username(username)

    if not user or not user.get("is_active"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario no encontrado o inactivo",
        )

    new_access_token = create_access_token(username)
    new_refresh_token = create_refresh_token(username)

    log.info("token_refreshed", username=username)

    return TokenResponse(access_token=new_access_token, refresh_token=new_refresh_token)


@router.get("/me", response_model=UserResponse)
async def me(current_user: dict = Depends(get_current_user)) -> UserResponse:
    """
    Retorna los datos del usuario autenticado actual.
    Útil para que el frontend verifique si el token sigue siendo válido.
    """
    return UserResponse(**current_user)
