# =============================================================================
# VIDATECH WIFI — Packages API
# backend/api/packages.py
# =============================================================================

import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel, condecimal, conint

from auth.dependencies import require_admin
from db import get_db
from utils import utcnow

logger = logging.getLogger("vidatech.packages")
router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class PackageCreate(BaseModel):
    name: str
    description: Optional[str] = None
    price_kes: float
    duration_hours: int
    download_kbps: int
    upload_kbps: int
    max_devices: int = 1
    location_id: Optional[str] = None


class PackageUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    price_kes: Optional[float] = None
    duration_hours: Optional[int] = None
    download_kbps: Optional[int] = None
    upload_kbps: Optional[int] = None
    max_devices: Optional[int] = None
    status: Optional[str] = None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/")
async def list_packages(active_only: bool = True):
    """Public — customer portal uses this to show available packages."""
    db = get_db()
    query = db.table("packages").select("*")
    if active_only:
        query = query.eq("status", "active")
    result = query.order("price_kes").execute()
    return result.data


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_package(body: PackageCreate, admin=Depends(require_admin)):
    db = get_db()

    if body.price_kes <= 0:
        raise HTTPException(status_code=400, detail="Price must be greater than 0.")
    if body.duration_hours <= 0:
        raise HTTPException(status_code=400, detail="Duration must be greater than 0.")

    result = db.table("packages").insert({
        "name": body.name,
        "description": body.description,
        "price_kes": body.price_kes,
        "duration_hours": body.duration_hours,
        "download_kbps": body.download_kbps,
        "upload_kbps": body.upload_kbps,
        "max_devices": body.max_devices,
        "location_id": body.location_id,
        "status": "active",
    }).execute()

    db.table("audit_logs").insert({
        "actor_id": admin["sub"],
        "actor_role": admin["role"],
        "action": "create",
        "target_table": "packages",
        "target_id": result.data[0]["id"],
        "description": f"Created package '{body.name}' at KES {body.price_kes}.",
    }).execute()

    return result.data[0]


@router.patch("/{package_id}")
async def update_package(package_id: str, body: PackageUpdate, admin=Depends(require_admin)):
    db = get_db()
    updates = {k: v for k, v in body.model_dump().items() if v is not None}

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update.")

    result = db.table("packages").update(updates).eq("id", package_id).execute()

    if not result.data:
        raise HTTPException(status_code=404, detail="Package not found.")

    db.table("audit_logs").insert({
        "actor_id": admin["sub"],
        "actor_role": admin["role"],
        "action": "update",
        "target_table": "packages",
        "target_id": package_id,
        "description": f"Updated package fields: {list(updates.keys())}",
        "new_value": updates,
    }).execute()

    return result.data[0]


@router.delete("/{package_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_package(package_id: str, admin=Depends(require_admin)):
    """Soft delete — sets deleted_at instead of removing the row."""
    db = get_db()
    result = db.table("packages").update({
        "deleted_at": utcnow().isoformat(),
        "status": "inactive",
    }).eq("id", package_id).execute()

    if not result.data:
        raise HTTPException(status_code=404, detail="Package not found.")

    db.table("audit_logs").insert({
        "actor_id": admin["sub"],
        "actor_role": admin["role"],
        "action": "delete",
        "target_table": "packages",
        "target_id": package_id,
        "description": "Package soft-deleted.",
    }).execute()
