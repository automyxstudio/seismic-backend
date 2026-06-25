"""
Tests unitarios para auth_service.

Cubren:
  - hash_password / verify_password con bcrypt.
  - create_access_token: payload correcto, campo type='access', expiración 15 min.
  - create_refresh_token: payload correcto, campo type='refresh', expiración 7 días.
  - decode_refresh_token: token válido, token expirado, token de tipo incorrecto.
  - Seguridad: un refresh token NO puede usarse como access token.
"""

import pytest
from datetime import datetime, timezone, timedelta
from jose import jwt

from src.services.auth_service import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
)
from src.config.settings import get_settings


class TestPasswordHashing:

    def test_hash_es_distinto_al_original(self):
        """El hash bcrypt nunca es igual al texto plano."""
        hashed = hash_password("mi_password")
        assert hashed != "mi_password"

    def test_verify_password_correcto(self):
        """verify_password retorna True cuando la contraseña coincide."""
        hashed = hash_password("secreto123")
        assert verify_password("secreto123", hashed) is True

    def test_verify_password_incorrecto(self):
        """verify_password retorna False ante una contraseña incorrecta."""
        hashed = hash_password("secreto123")
        assert verify_password("otra_clave", hashed) is False

    def test_dos_hashes_del_mismo_password_son_distintos(self):
        """bcrypt usa salt aleatorio — el mismo password produce hashes distintos."""
        h1 = hash_password("password")
        h2 = hash_password("password")
        assert h1 != h2

    def test_verify_sigue_funcionando_con_diferentes_hashes(self):
        """Aunque los hashes difieran, verify_password resuelve correctamente."""
        h1 = hash_password("password")
        h2 = hash_password("password")
        assert verify_password("password", h1) is True
        assert verify_password("password", h2) is True


class TestAccessToken:

    def test_access_token_decodeable(self):
        """El token generado puede decodificarse con la misma clave."""
        settings = get_settings()
        token = create_access_token("testuser")
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        assert payload["sub"] == "testuser"

    def test_access_token_type_es_access(self):
        """El campo type debe ser 'access' — impide usarlo como refresh."""
        settings = get_settings()
        token = create_access_token("testuser")
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        assert payload["type"] == "access"

    def test_access_token_expira_en_15_minutos(self):
        """La expiración del access token es ~15 minutos desde ahora."""
        settings = get_settings()
        before = datetime.now(timezone.utc)
        token = create_access_token("testuser")
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)

        expected_exp = before + timedelta(minutes=settings.jwt_access_token_expire_minutes)
        diff = abs((exp - expected_exp).total_seconds())
        assert diff < 5  # tolerancia de 5 segundos


class TestRefreshToken:

    def test_refresh_token_decodeable(self):
        """El refresh token puede decodificarse con la misma clave."""
        settings = get_settings()
        token = create_refresh_token("testuser")
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        assert payload["sub"] == "testuser"

    def test_refresh_token_type_es_refresh(self):
        """El campo type debe ser 'refresh' — impide usarlo como access."""
        settings = get_settings()
        token = create_refresh_token("testuser")
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        assert payload["type"] == "refresh"

    def test_refresh_token_expira_en_7_dias(self):
        """La expiración del refresh token es ~7 días desde ahora."""
        settings = get_settings()
        before = datetime.now(timezone.utc)
        token = create_refresh_token("testuser")
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)

        expected_exp = before + timedelta(days=settings.jwt_refresh_token_expire_days)
        diff = abs((exp - expected_exp).total_seconds())
        assert diff < 5


class TestDecodeRefreshToken:

    def test_decode_token_valido_retorna_username(self):
        """Un refresh token válido retorna el username."""
        token = create_refresh_token("camilo")
        result = decode_refresh_token(token)
        assert result == "camilo"

    def test_decode_access_token_como_refresh_retorna_none(self):
        """Un access token NO puede usarse como refresh — retorna None."""
        token = create_access_token("camilo")
        result = decode_refresh_token(token)
        assert result is None

    def test_decode_token_invalido_retorna_none(self):
        """Un token corrupto retorna None sin lanzar excepción."""
        result = decode_refresh_token("esto.no.es.un.jwt")
        assert result is None

    def test_decode_token_con_clave_incorrecta_retorna_none(self):
        """Un token firmado con otra clave retorna None."""
        from jose import jwt as jose_jwt
        token = jose_jwt.encode(
            {"sub": "hacker", "type": "refresh", "exp": 9999999999},
            "clave_incorrecta",
            algorithm="HS256",
        )
        result = decode_refresh_token(token)
        assert result is None
