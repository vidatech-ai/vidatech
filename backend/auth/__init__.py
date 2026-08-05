# =============================================================================
# VIDATECH WIFI — Auth Router
# backend/auth/__init__.py
# =============================================================================

import logging
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from config import get_settings
from auth.jwt import create_access_token, create_refresh_token, decode_token
from utils import verify_password, utcnow, mask_phone

logger = logging.getLogger("vidatech.auth")
settings = get_settings()
router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    phone: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    role: str


class RefreshRequest(BaseModel):
    refresh_token: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, request: Request):
    from db import get_db

    db = get_db()
    ip = request.client.host

    # Fetch user by phone
    result = db.table("users").select("*").eq("phone", body.phone).single().execute()
    user = result.data if result.data else None

    if not user or user.get("role") not in ("admin", "operator"):
        logger.warning(f"Failed login attempt for phone {mask_phone(body.phone)} from {ip}")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials.")

    # Check lockout
    if user.get("locked_until"):
        from datetime import datetime, timezone
        locked_until = datetime.fromisoformat(user["locked_until"])
        if utcnow() < locked_until:
            raise HTTPException(
                status_code=status.HTTP_423_LOCKED,
                detail=f"Account locked. Try again after {locked_until.strftime('%H:%M UTC')}.",
            )

    # Verify password
    if not verify_password(body.password, user["password_hash"]):
        # Increment failed login count
        new_count = user["failed_login_count"] + 1
        update = {"failed_login_count": new_count}

        if new_count >= settings.MAX_FAILED_LOGINS:
            from datetime import timedelta
            locked_until = utcnow() + timedelta(minutes=settings.LOCKOUT_DURATION_MINUTES)
            update["locked_until"] = locked_until.isoformat()
            logger.warning(f"Account locked for {mask_phone(body.phone)} after {new_count} failed attempts.")

        db.table("users").update(update).eq("id", user["id"]).execute()

        # Log security event
        db.table("security_events").insert({
            "user_id": user["id"],
            "severity": "warning",
            "event_type": "failed_login",
            "description": f"Failed login attempt {new_count}/{settings.MAX_FAILED_LOGINS}.",
            "source_ip": ip,
        }).execute()

        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials.")

    # Successful login — reset failed count
    db.table("users").update({
        "failed_login_count": 0,
        "locked_until": None,
        "last_login_at": utcnow().isoformat(),
        "last_login_ip": ip,
    }).eq("id", user["id"]).execute()

    # Audit log
    db.table("audit_logs").insert({
        "actor_id": user["id"],
        "actor_role": user["role"],
        "action": "login",
        "description": f"Admin login from {ip}.",
        "ip_address": ip,
    }).execute()

    access_token  = create_access_token(subject=user["id"], role=user["role"])
    refresh_token = create_refresh_token(subject=user["id"], role=user["role"])

    logger.info(f"Successful login: {mask_phone(body.phone)} ({user['role']}) from {ip}")

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        role=user["role"],
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshRequest):
    payload = decode_token(body.refresh_token)

    if not payload or payload.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token.")

    access_token  = create_access_token(subject=payload["sub"], role=payload["role"])
    refresh_token = create_refresh_token(subject=payload["sub"], role=payload["role"])

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        role=payload["role"],
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout():
    # JWT is stateless — client simply discards the token.
    # Future: maintain a token blacklist in Redis if needed.
    return
