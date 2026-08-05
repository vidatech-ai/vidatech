# =============================================================================
# VIDATECH WIFI — Auth Dependencies
# backend/auth/dependencies.py
# =============================================================================

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from auth.jwt import decode_token

bearer_scheme = HTTPBearer()


def _get_current_user(credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme)) -> dict:
    token = credentials.credentials
    payload = decode_token(token)

    if not payload or payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return payload


def require_auth(payload: dict = Depends(_get_current_user)) -> dict:
    """Any authenticated user."""
    return payload


def require_admin(payload: dict = Depends(_get_current_user)) -> dict:
    """Admin only."""
    if payload.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required.",
        )
    return payload


def require_operator(payload: dict = Depends(_get_current_user)) -> dict:
    """Admin or operator."""
    if payload.get("role") not in ("admin", "operator"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Operator access required.",
        )
    return payload
