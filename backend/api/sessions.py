# =============================================================================
# VIDATECH WIFI — Sessions API
# backend/api/sessions.py
# =============================================================================

import logging
from fastapi import APIRouter, HTTPException, Depends, status
from auth.dependencies import require_admin
from db import get_db
from utils import utcnow

logger = logging.getLogger("vidatech.sessions")
router = APIRouter()


@router.get("/active")
async def active_sessions(admin=Depends(require_admin)):
    """All currently active sessions — main dashboard feed."""
    db = get_db()
    result = db.table("active_sessions_view").select("*").execute()
    return result.data


@router.get("/")
async def all_sessions(limit: int = 100, admin=Depends(require_admin)):
    db = get_db()
    result = db.table("sessions").select(
        "*, users(full_name, phone), packages(name)"
    ).order("created_at", desc=True).limit(limit).execute()
    return result.data


@router.post("/{session_id}/terminate")
async def terminate_session(session_id: str, admin=Depends(require_admin)):
    """Admin manually terminates a session."""
    db = get_db()

    result = db.table("sessions").update({
        "status": "terminated",
        "terminated_at": utcnow().isoformat(),
        "termination_reason": "admin_action",
    }).eq("id", session_id).eq("status", "active").execute()

    if not result.data:
        raise HTTPException(status_code=404, detail="Active session not found.")

    session = result.data[0]

    # Block device
    db.table("devices").update({"status": "blocked"}).eq("mac_address", session["mac_address"]).execute()

    db.table("audit_logs").insert({
        "actor_id": admin["sub"],
        "actor_role": admin["role"],
        "action": "session_end",
        "target_table": "sessions",
        "target_id": session_id,
        "description": "Session manually terminated by admin.",
    }).execute()

    logger.info(f"Session {session_id} terminated by admin {admin['sub']}")
    return {"message": "Session terminated."}


@router.get("/check/{mac_address}")
async def check_session(mac_address: str):
    """
    Portal gateway calls this to check if a device has an active paid session.
    Returns allowed: true/false.
    """
    db = get_db()
    mac_address = mac_address.lower()

    result = db.table("sessions").select("id, status, expires_at").eq(
        "mac_address", mac_address
    ).eq("status", "active").order("expires_at", desc=True).limit(1).execute()

    if not result.data:
        return {"allowed": False}

    session = result.data[0]

    if session["expires_at"] < utcnow().isoformat():
        # Expire it
        db.table("sessions").update({
            "status": "expired",
            "terminated_at": utcnow().isoformat(),
            "termination_reason": "expired",
        }).eq("id", session["id"]).execute()
        return {"allowed": False}

    return {"allowed": True, "expires_at": session["expires_at"]}
