# =============================================================================
# VIDATECH WIFI — Sessions API
# backend/api/sessions.py
# =============================================================================

import logging
from fastapi import APIRouter, HTTPException, Depends, Request, status
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


@router.get("/reconnect/{mpesa_code}")
async def reconnect_by_mpesa_code(mpesa_code: str, request: Request):
    db = get_db()
    mpesa_code = mpesa_code.strip().upper()

    pay_result = db.table("payments").select(
        "id, phone, mac_address, status, packages(name, duration_hours)"
    ).eq("mpesa_transaction_code", mpesa_code).limit(1).execute()

    if not pay_result.data:
        return {"allowed": False, "reason": "code_not_found"}

    payment = pay_result.data[0]
    if payment["status"] != "confirmed":
        return {"allowed": False, "reason": "payment_not_confirmed"}

    sess_result = db.table("sessions").select(
        "id, expires_at, mac_address, packages(name)"
    ).eq("payment_id", payment["id"]).eq("status", "active").limit(1).execute()

    if not sess_result.data:
        return {"allowed": False, "reason": "session_expired"}

    session = sess_result.data[0]
    if session["expires_at"] < utcnow().isoformat():
        return {"allowed": False, "reason": "session_expired"}

    client_ip = (
        request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        or request.client.host
    )
    dev_result = db.table("devices").select("mac_address").eq(
        "ip_address", client_ip
    ).limit(1).execute()

    new_mac = dev_result.data[0]["mac_address"] if dev_result.data else None

    if new_mac and new_mac != session["mac_address"]:
        db.table("sessions").update({
            "mac_address": new_mac.lower()
        }).eq("id", session["id"]).execute()
        db.table("devices").upsert({
            "mac_address": new_mac.lower(),
            "ip_address": client_ip,
            "status": "allowed",
            "last_seen_at": utcnow().isoformat(),
        }, on_conflict="mac_address").execute()

    return {
        "allowed": True,
        "expires_at": session["expires_at"],
        "package": session["packages"]["name"] if session.get("packages") else "—",
        "phone": payment["phone"],
    }
async def check_session(mac_address: str):
    """
    Portal gateway calls this to check if a device has an active paid session.
    Returns allowed: true/false.
    """
    db = get_db()
    mac_address = mac_address.lower()

    result = db.table("sessions").select(
        "id, status, expires_at, created_at, packages(name)"
    ).eq(
        "mac_address", mac_address
    ).order("expires_at", desc=True).limit(1).execute()

    if not result.data:
        return {"allowed": False, "reason": "not_found"}

    session = result.data[0]

    if session["expires_at"] < utcnow().isoformat():
        db.table("sessions").update({
            "status": "expired",
            "terminated_at": utcnow().isoformat(),
            "termination_reason": "expired",
        }).eq("id", session["id"]).execute()
        return {
            "allowed": False,
            "reason": "expired",
            "paid_at": session["created_at"],
            "expired_at": session["expires_at"],
            "package": session["packages"]["name"] if session.get("packages") else "—",
        }

    return {
        "allowed": True,
        "expires_at": session["expires_at"],
        "paid_at": session["created_at"],
        "package": session["packages"]["name"] if session.get("packages") else "—",
    }
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
