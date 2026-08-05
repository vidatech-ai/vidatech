# =============================================================================
# VIDATECH WIFI — Devices API
# backend/api/devices.py
# =============================================================================

import logging
from fastapi import APIRouter, HTTPException, Depends
from auth.dependencies import require_admin
from db import get_db
from utils import utcnow

logger = logging.getLogger("vidatech.devices")
router = APIRouter()


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
    }).eq("device_id", device_id).eq("status", "active").execute()

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
    result = db.table("devices").update({"status": "allowed"}).eq("id", device_id).execute()

    if not result.data:
        raise HTTPException(status_code=404, detail="Device not found.")

    db.table("audit_logs").insert({
        "actor_id": admin["sub"],
        "actor_role": admin["role"],
        "action": "unblock",
        "target_table": "devices",
        "target_id": device_id,
        "description": f"Device allowed by admin.",
    }).execute()

    return {"message": "Device allowed."}
