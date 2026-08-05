# =============================================================================
# VIDATECH WIFI — Users API
# backend/api/users.py
# =============================================================================

import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel

from auth.dependencies import require_admin
from db import get_db
from utils import utcnow, hash_password, normalise_phone, normalise_mac

logger = logging.getLogger("vidatech.users")
router = APIRouter()


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None
    is_whitelisted: Optional[bool] = None


@router.get("/")
async def list_users(admin=Depends(require_admin)):
    db = get_db()
    result = db.table("users").select(
        "id, full_name, phone, status, role, is_whitelisted, last_login_at, created_at"
    ).is_("deleted_at", "null").order("created_at", desc=True).execute()
    return result.data


@router.get("/{user_id}")
async def get_user(user_id: str, admin=Depends(require_admin)):
    db = get_db()
    result = db.table("users").select("*").eq("id", user_id).single().execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="User not found.")
    return result.data


@router.patch("/{user_id}")
async def update_user(user_id: str, body: UserUpdate, admin=Depends(require_admin)):
    db = get_db()
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update.")

    result = db.table("users").update(updates).eq("id", user_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="User not found.")

    db.table("audit_logs").insert({
        "actor_id": admin["sub"],
        "actor_role": admin["role"],
        "action": "update",
        "target_table": "users",
        "target_id": user_id,
        "description": f"Updated user fields: {list(updates.keys())}",
        "new_value": updates,
    }).execute()

    return result.data[0]


@router.post("/{user_id}/suspend")
async def suspend_user(user_id: str, admin=Depends(require_admin)):
    db = get_db()
    db.table("users").update({"status": "suspended"}).eq("id", user_id).execute()

    # Terminate all active sessions
    db.table("sessions").update({
        "status": "terminated",
        "terminated_at": utcnow().isoformat(),
        "termination_reason": "admin_action",
    }).eq("user_id", user_id).eq("status", "active").execute()

    db.table("audit_logs").insert({
        "actor_id": admin["sub"],
        "actor_role": admin["role"],
        "action": "suspend",
        "target_table": "users",
        "target_id": user_id,
        "description": "User suspended by admin.",
    }).execute()

    return {"message": "User suspended."}


@router.post("/{user_id}/unblock")
async def unblock_user(user_id: str, admin=Depends(require_admin)):
    db = get_db()
    db.table("users").update({
        "status": "active",
        "failed_login_count": 0,
        "locked_until": None,
    }).eq("id", user_id).execute()

    db.table("audit_logs").insert({
        "actor_id": admin["sub"],
        "actor_role": admin["role"],
        "action": "unblock",
        "target_table": "users",
        "target_id": user_id,
        "description": "User unblocked by admin.",
    }).execute()

    return {"message": "User unblocked."}
