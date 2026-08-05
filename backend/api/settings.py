# =============================================================================
# VIDATECH WIFI — Settings API
# backend/api/settings.py
# =============================================================================

import logging
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from auth.dependencies import require_admin
from db import get_db

logger = logging.getLogger("vidatech.settings")
router = APIRouter()


class SettingUpdate(BaseModel):
    value: str


@router.get("/")
async def get_settings(admin=Depends(require_admin)):
    db = get_db()
    result = db.table("settings").select("key, value, description, is_sensitive").execute()
    # Mask sensitive values
    for row in result.data:
        if row["is_sensitive"]:
            row["value"] = "********"
    return result.data


@router.patch("/{key}")
async def update_setting(key: str, body: SettingUpdate, admin=Depends(require_admin)):
    db = get_db()
    db.table("settings").update({
        "value": body.value,
        "updated_by": admin["sub"],
    }).eq("key", key).execute()

    db.table("audit_logs").insert({
        "actor_id": admin["sub"],
        "actor_role": admin["role"],
        "action": "update",
        "target_table": "settings",
        "description": f"Setting '{key}' updated.",
    }).execute()

    return {"message": f"Setting '{key}' updated."}
