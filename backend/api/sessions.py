# =============================================================================
# VIDATECH WIFI — Sessions API
# backend/api/sessions.py
# =============================================================================
import logging
from fastapi import APIRouter, HTTPException, Depends, Request, status
from auth.dependencies import require_admin
from db import get_db
from utils import utcnow, normalise_phone

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


@router.get("/reconnect-by-phone")
async def reconnect_by_phone(phone: str, request: Request):
    """
    Client enters phone number to reconnect.
    - Finds all active paid sessions for that phone
    - Counts how many device slots are available
    - Authorizes new MAC if slots are available
    - Blocks reconnect if all slots are in use by online devices
    """
    db = get_db()
    phone = normalise_phone(phone)
    if not phone:
        return {"allowed": False, "reason": "invalid_phone"}

    client_ip = (
        request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        or request.client.host
    )

    # Get new MAC from requesting IP
    dev_result = db.table("devices").select("mac_address").eq(
        "ip_address", client_ip
    ).limit(1).execute()
    new_mac = dev_result.data[0]["mac_address"].lower() if dev_result.data else None

    # Find all active sessions for this phone
    sess_result = db.table("sessions").select(
        "id, expires_at, mac_address, packages(name)"
    ).eq("phone", phone).eq("status", "active").order("expires_at", desc=True).execute()

    if not sess_result.data:
        # Try via payments table
        pay_result = db.table("payments").select("id").eq(
            "phone", phone
        ).eq("status", "confirmed").execute()
        if not pay_result.data:
            return {"allowed": False, "reason": "no_active_sessions"}
        payment_ids = [p["id"] for p in pay_result.data]
        sess_result2 = db.table("sessions").select(
            "id, expires_at, mac_address, packages(name)"
        ).in_("payment_id", payment_ids).eq("status", "active").execute()
        if not sess_result2.data:
            return {"allowed": False, "reason": "no_active_sessions"}
        sessions = sess_result2.data
    else:
        sessions = sess_result.data

    now = utcnow().isoformat()
    active_sessions = [s for s in sessions if s["expires_at"] > now]

    if not active_sessions:
        return {"allowed": False, "reason": "session_expired"}

    # Check if new MAC already has a session
    for s in active_sessions:
        if s["mac_address"] and s["mac_address"].lower() == new_mac:
            return {
                "allowed": True,
                "expires_at": s["expires_at"],
                "package": s["packages"]["name"] if s.get("packages") else "—",
                "phone": phone,
                "slots_used": len(active_sessions),
                "slots_total": len(active_sessions),
            }

    # Count slots: total paid sessions = total device slots
    total_slots = len(active_sessions)

    # Find sessions with MACs not currently online in nodogsplash
    # We do this by checking which MACs have been seen recently
    assigned_macs = [s["mac_address"] for s in active_sessions if s["mac_address"]]

    # Find available slot — session whose MAC is offline or unassigned
    available_session = None
    for s in active_sessions:
        if not s["mac_address"]:
            available_session = s
            break

    if not available_session:
        # All slots have MACs — check which ones are inactive (not seen in last 5 mins)
        from utils import utcnow as _now
        import datetime
        five_mins_ago = (datetime.datetime.utcnow() - datetime.timedelta(minutes=5)).isoformat()
        for s in active_sessions:
            if s["mac_address"]:
                dev = db.table("devices").select("last_seen_at").eq(
                    "mac_address", s["mac_address"]
                ).limit(1).execute()
                if dev.data and dev.data[0]["last_seen_at"] < five_mins_ago:
                    available_session = s
                    break

    if not available_session:
        return {
            "allowed": False,
            "reason": "all_slots_in_use",
            "slots_total": total_slots,
            "message": f"All {total_slots} device slot(s) are currently in use. Disconnect another device first."
        }

    # Assign new MAC to available session
    if new_mac:
        db.table("sessions").update({
            "mac_address": new_mac
        }).eq("id", available_session["id"]).execute()

        db.table("devices").upsert({
            "mac_address": new_mac,
            "ip_address": client_ip,
            "status": "allowed",
            "last_seen_at": utcnow().isoformat(),
        }, on_conflict="mac_address").execute()

    return {
        "allowed": True,
        "expires_at": available_session["expires_at"],
        "package": available_session["packages"]["name"] if available_session.get("packages") else "—",
        "phone": phone,
        "slots_used": len([s for s in active_sessions if s["mac_address"]]),
        "slots_total": total_slots,
    }


@router.get("/check/{mac_address:path}")
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
