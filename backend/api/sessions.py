# =============================================================================
# VIDATECH WIFI — Sessions API
# backend/api/sessions.py
# =============================================================================
import logging
import datetime
from fastapi import APIRouter, HTTPException, Depends, Request, status
from auth.dependencies import require_admin
from db import get_db
from utils import utcnow, normalise_phone

logger = logging.getLogger("vidatech.sessions")
router = APIRouter()


@router.get("/active")
async def active_sessions(admin=Depends(require_admin)):
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
    db = get_db()
    result = db.table("sessions").update({
        "status": "terminated",
        "terminated_at": utcnow().isoformat(),
        "termination_reason": "admin_action",
    }).eq("id", session_id).eq("status", "active").execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Active session not found.")
    session = result.data[0]
    db.table("devices").update({"status": "unknown"}).eq("mac_address", session["mac_address"]).execute()
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
    db = get_db()
    phone = normalise_phone(phone)
    if not phone:
        return {"allowed": False, "reason": "invalid_phone"}
    client_ip = (
        request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        or request.client.host
    )
    dev_result = db.table("devices").select("mac_address").eq("ip_address", client_ip).limit(1).execute()
    new_mac = dev_result.data[0]["mac_address"].lower() if dev_result.data else None
    sess_result = db.table("sessions").select(
        "id, expires_at, mac_address, packages(name)"
    ).eq("phone", phone).eq("status", "active").order("expires_at", desc=True).execute()
    if not sess_result.data:
        pay_result = db.table("payments").select("id").eq("phone", phone).eq("status", "confirmed").execute()
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
    for s in active_sessions:
        if s["mac_address"] and s["mac_address"].lower() == new_mac:
            return {
                "allowed": True,
                "expires_at": s["expires_at"],
                "package": s["packages"]["name"] if s.get("packages") else "—",
                "phone": phone,
                "mac_address": new_mac,
                "slots_used": len(active_sessions),
                "slots_total": len(active_sessions),
            }
    total_slots = len(active_sessions)
    available_session = None
    for s in active_sessions:
        if not s["mac_address"]:
            available_session = s
            break
    if not available_session:
        five_mins_ago = (datetime.datetime.utcnow() - datetime.timedelta(seconds=30)).isoformat()
        for s in active_sessions:
            if s["mac_address"]:
                dev = db.table("devices").select("last_seen_at").eq("mac_address", s["mac_address"]).limit(1).execute()
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
    if new_mac:
        old_mac = available_session.get("mac_address")
        if old_mac and old_mac != new_mac:
            import httpx
            try:
                async with httpx.AsyncClient() as hclient:
                    await hclient.get(f"http://192.168.2.1/cgi-bin/auth?deauth={old_mac}", timeout=3)
            except Exception:
                pass
        db.table("sessions").update({"mac_address": new_mac}).eq("id", available_session["id"]).execute()
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
        "mac_address": new_mac,
        "slots_used": len([s for s in active_sessions if s["mac_address"]]),
        "slots_total": total_slots,
    }


@router.get("/active-macs")
async def active_macs():
    db = get_db()
    now = utcnow().isoformat()
    blocked_result = db.table("devices").select("mac_address").eq("status", "blocked").execute()
    blocked = set(d["mac_address"] for d in blocked_result.data if d["mac_address"]) if blocked_result.data else set()
    result = db.table("sessions").select("mac_address").eq("status", "active").gt("expires_at", now).execute()
    macs = [s["mac_address"] for s in result.data if s["mac_address"] and s["mac_address"] not in blocked]
    return {"macs": macs}


@router.get("/expired-macs")
async def expired_macs():
    db = get_db()
    now = utcnow().isoformat()
    two_mins_ago = (datetime.datetime.utcnow() - datetime.timedelta(minutes=2)).isoformat()
    expired_result = db.table("sessions").select("mac_address").eq("status", "active").lt("expires_at", now).execute()
    expired = []
    if expired_result.data:
        expired = [s["mac_address"] for s in expired_result.data if s["mac_address"]]
        db.table("sessions").update({
            "status": "expired",
            "terminated_at": now,
            "termination_reason": "expired",
        }).eq("status", "active").lt("expires_at", now).execute()
    terminated_result = db.table("sessions").select("mac_address").eq("status", "terminated").gt("terminated_at", two_mins_ago).execute()
    terminated = [s["mac_address"] for s in terminated_result.data if s["mac_address"]] if terminated_result.data else []
    blocked_result = db.table("devices").select("mac_address").eq("status", "blocked").gt("last_seen_at", two_mins_ago).execute()
    blocked = [d["mac_address"] for d in blocked_result.data if d["mac_address"]] if blocked_result.data else []
    all_macs = list(set(expired + terminated + blocked))
    return {"macs": all_macs}


@router.get("/pending-grants")
async def pending_grants():
    """
    Router polls this every 5 seconds.
    Returns confirmed payments matched with recently seen unknown devices.
    """
    db = get_db()
    two_mins_ago = (datetime.datetime.utcnow() - datetime.timedelta(minutes=2)).isoformat()
    five_mins_ago = (datetime.datetime.utcnow() - datetime.timedelta(minutes=5)).isoformat()

    payments = db.table("payments").select("id, phone").eq(
        "status", "confirmed"
    ).eq("mac_address", "00:00:00:00:00:00").gt("confirmed_at", five_mins_ago).execute()

    if not payments.data:
        return {"grants": []}

    devices = db.table("devices").select("mac_address, ip_address").in_(
        "status", ["unknown", "active"]
    ).gt("last_seen_at", two_mins_ago).execute()

    if not devices.data:
        return {"grants": []}

    grants = []
    for p in payments.data:
        for d in devices.data:
            mac = d.get("mac_address")
            if mac and mac != "00:00:00:00:00:00":
                grants.append({
                    "payment_id": p["id"],
                    "mac": mac,
                })
                break

    return {"grants": grants}


@router.post("/confirm-grant")
async def confirm_grant(request: Request):
    """Router calls this after granting a MAC to update the payment and session."""
    body = await request.json()
    payment_id = body.get("payment_id")
    mac = (body.get("mac") or "").lower().strip()
    db = get_db()
    if not payment_id or not mac:
        return {"ok": False, "error": "missing fields"}
    db.table("payments").update({"mac_address": mac}).eq("id", payment_id).execute()
    db.table("sessions").update({"mac_address": mac}).eq("payment_id", payment_id).execute()
    db.table("devices").upsert({"mac_address": mac, "status": "allowed"}, on_conflict="mac_address").execute()
    logger.info(f"confirm-grant: {mac} for payment {payment_id}")
    return {"ok": True}


@router.post("/deauth/{mac_address:path}")
async def deauth_client(mac_address: str, admin=Depends(require_admin)):
    import httpx
    mac_address = mac_address.lower()
    db = get_db()
    try:
        async with httpx.AsyncClient() as client:
            await client.get(f"http://192.168.2.1/cgi-bin/auth?deauth={mac_address}", timeout=3)
    except Exception:
        pass
    db.table("sessions").update({
        "status": "terminated",
        "terminated_at": utcnow().isoformat(),
        "termination_reason": "admin_action",
    }).eq("mac_address", mac_address).eq("status", "active").execute()
    db.table("devices").update({"status": "blocked"}).eq("mac_address", mac_address).execute()
    db.table("audit_logs").insert({
        "actor_id": admin["sub"],
        "actor_role": admin["role"],
        "action": "deauth",
        "target_table": "devices",
        "target_id": mac_address,
        "description": f"Admin deauthed {mac_address}.",
    }).execute()
    return {"message": f"Deauthed {mac_address}"}


@router.post("/grant/{mac_address:path}")
async def grant_session(mac_address: str, request: Request, admin=Depends(require_admin)):
    db = get_db()
    body = await request.json()
    minutes = int(body.get("minutes", 60))
    mac_address = mac_address.lower()
    expires = (datetime.datetime.utcnow() + datetime.timedelta(minutes=minutes)).isoformat()
    db.table("sessions").insert({
        "mac_address": mac_address,
        "status": "active",
        "started_at": utcnow().isoformat(),
        "expires_at": expires,
        "phone": "admin_grant",
        "termination_reason": None,
    }).execute()
    db.table("devices").update({"status": "allowed"}).eq("mac_address", mac_address).execute()
    db.table("audit_logs").insert({
        "actor_id": admin["sub"],
        "actor_role": admin["role"],
        "action": "grant",
        "target_table": "sessions",
        "target_id": mac_address,
        "description": f"Admin granted {minutes} minutes to {mac_address}.",
    }).execute()
    logger.info(f"Admin granted {minutes}min to {mac_address}")
    return {"message": f"Granted {minutes} minutes to {mac_address}", "expires_at": expires}


@router.get("/check/{mac_address:path}")
async def check_session(mac_address: str):
    db = get_db()
    mac_address = mac_address.lower()
    result = db.table("sessions").select(
        "id, status, expires_at, created_at, packages(name)"
    ).eq("mac_address", mac_address).order("expires_at", desc=True).limit(1).execute()
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
