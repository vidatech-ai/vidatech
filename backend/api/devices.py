# =============================================================================
# VIDATECH WIFI — Devices API
# backend/api/devices.py
# =============================================================================

import logging
from fastapi import APIRouter, HTTPException, Depends, Request
from auth.dependencies import require_admin
from db import get_db
from utils import utcnow

logger = logging.getLogger("vidatech.devices")
router = APIRouter()


@router.post("/heartbeat")
async def device_heartbeat(request: Request):
    """Called by router when a device connects. Registers MAC+IP."""
    body = await request.json()
    mac = (body.get("mac_address") or "").lower().strip()
    ip = body.get("ip_address") or ""
    if not mac:
        return {"ok": False}
    db = get_db()
    existing = db.table("devices").select("id").eq("mac_address", mac).limit(1).execute()
    if existing.data:
        db.table("devices").update({
            "ip_address": ip,
            "last_seen_at": utcnow().isoformat(),
            "status": existing.data[0].get("status", "unknown"),
        }).eq("mac_address", mac).execute()
    else:
        db.table("devices").insert({
            "mac_address": mac,
            "ip_address": ip,
            "status": "unknown",
            "last_seen_at": utcnow().isoformat(),
        }).execute()
    return {"ok": True}


_router_status_cache = {"clients": [], "status": {}, "updated_at": None}

@router.post("/router-status")
async def push_router_status(request: Request):
    """Called by router agent every 5 seconds to push connected clients and status."""
    global _router_status_cache
    body = await request.json()
    body["updated_at"] = utcnow().isoformat()
    _router_status_cache = body

    # Update last_seen_at for each connected device in DB
    db = get_db()
    for client in body.get("clients", []):
        mac = (client.get("mac") or "").lower().strip()
        ip = client.get("ip") or ""
        if not mac:
            continue
        existing = db.table("devices").select("id", "status").eq("mac_address", mac).limit(1).execute()
        if existing.data:
            db.table("devices").update({
                "ip_address": ip,
                "last_seen_at": utcnow().isoformat(),
            }).eq("mac_address", mac).execute()
        else:
            db.table("devices").insert({
                "mac_address": mac,
                "ip_address": ip,
                "status": "unknown",
                "last_seen_at": utcnow().isoformat(),
            }).execute()

    return {"ok": True}

@router.get("/router-status")
async def router_status():
    """Returns cached router status — live clients and router health."""
    return _router_status_cache


@router.post("/authorize")
async def authorize_device(request: Request):
    """
    Called by frontend after payment confirmed.
    Backend finds the client token from router and authorizes it.
    """
    import httpx
    body = await request.json()
    mac_address = (body.get("mac_address") or "").lower().strip()
    try:
        async with httpx.AsyncClient() as client:
            # Get live router clients
            res = await client.get("http://192.168.2.1/cgi-bin/ndsstatus", timeout=5)
            data = res.json()
            clients = data.get("clients", {})
            # Find token for this MAC
            token = None
            for mac, info in clients.items():
                if mac.lower() == mac_address:
                    token = info.get("token")
                    break
            if token:
                await client.get(f"http://192.168.2.1/cgi-bin/auth?tok={token}", timeout=5)
                return {"authorized": True, "token": token}
            return {"authorized": False, "reason": "client_not_found"}
    except Exception as e:
        return {"authorized": False, "reason": str(e)}
@router.get("/my-mac")
async def my_mac(request: Request):
    """Returns the MAC address of the requesting device based on IP lookup in devices table."""
    db = get_db()
    client_ip = (
        request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        or request.client.host
    )
    result = db.table("devices").select("mac_address").eq("ip_address", client_ip).limit(1).execute()
    if result.data and result.data[0]["mac_address"] not in (None, "00:00:00:00:00:00"):
        return {"mac_address": result.data[0]["mac_address"]}
    return {"mac_address": None}

@router.get("/")
async def list_devices(admin=Depends(require_admin)):
    db = get_db()
    result = db.table("devices").select(
        "*, users(full_name, phone)"
    ).order("last_seen_at", desc=True).execute()
    return result.data


@router.post("/{device_id}/block")
async def block_device(device_id: str, admin=Depends(require_admin)):
    db = get_db()
    result = db.table("devices").update({"status": "blocked"}).eq("id", device_id).execute()

    if not result.data:
        raise HTTPException(status_code=404, detail="Device not found.")

    device = result.data[0]

    # Terminate any active session for this device
    db.table("sessions").update({
        "status": "terminated",
        "terminated_at": utcnow().isoformat(),
        "termination_reason": "device_blocked",
    }).eq("mac_address", device["mac_address"]).eq("status", "active").execute()

    db.table("audit_logs").insert({
        "actor_id": admin["sub"],
        "actor_role": admin["role"],
        "action": "block",
        "target_table": "devices",
        "target_id": device_id,
        "description": f"Device {device['mac_address']} blocked.",
    }).execute()

    return {"message": "Device blocked."}


@router.post("/{device_id}/allow")
async def allow_device(device_id: str, admin=Depends(require_admin)):
    db = get_db()
    result = db.table("devices").update({
        "status": "whitelisted"
    }).eq("id", device_id).execute()

    if not result.data:
        raise HTTPException(status_code=404, detail="Device not found.")

    db.table("audit_logs").insert({
        "actor_id": admin["sub"],
        "actor_role": admin["role"],
        "action": "unblock",
        "target_table": "devices",
        "target_id": device_id,
        "description": f"Device whitelisted by admin.",
    }).execute()

    return {"message": "Device whitelisted."}
