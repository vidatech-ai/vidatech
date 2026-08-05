# =============================================================================
# VIDATECH WIFI — Reports API
# backend/api/reports.py
# =============================================================================

import logging
from fastapi import APIRouter, Depends
from auth.dependencies import require_admin
from db import get_db
from utils import utcnow

logger = logging.getLogger("vidatech.reports")
router = APIRouter()


@router.get("/dashboard")
async def dashboard_summary(admin=Depends(require_admin)):
    """Single endpoint that powers the entire admin dashboard."""
    db = get_db()
    now = utcnow().isoformat()

    # Active sessions count
    active = db.table("sessions").select("id", count="exact").eq("status", "active").execute()

    # Today's revenue
    today = utcnow().date().isoformat()
    today_rev = db.table("payments").select("amount_kes").eq("status", "confirmed").gte("confirmed_at", today).execute()
    today_total = sum(p["amount_kes"] for p in today_rev.data)

    # Monthly revenue
    month_start = utcnow().replace(day=1).date().isoformat()
    month_rev = db.table("payments").select("amount_kes").eq("status", "confirmed").gte("confirmed_at", month_start).execute()
    month_total = sum(p["amount_kes"] for p in month_rev.data)

    # Recent payments (last 10)
    recent_payments = db.table("payments").select(
        "phone, amount_kes, status, mpesa_transaction_code, confirmed_at, packages(name)"
    ).order("created_at", desc=True).limit(10).execute()

    # Unread security alerts
    alerts = db.table("security_events").select("*").eq("is_resolved", False).order(
        "created_at", desc=True
    ).limit(5).execute()

    # Unread notifications
    notifs = db.table("notifications").select("*").eq("is_read", False).order(
        "created_at", desc=True
    ).limit(10).execute()

    # Package popularity
    pkg_sales = db.table("payments").select("packages(name), amount_kes").eq("status", "confirmed").execute()
    pkg_count: dict = {}
    for p in pkg_sales.data:
        name = p["packages"]["name"] if p["packages"] else "Unknown"
        pkg_count[name] = pkg_count.get(name, 0) + 1
    popular = sorted(pkg_count.items(), key=lambda x: x[1], reverse=True)

    return {
        "active_sessions": active.count,
        "revenue": {
            "today_kes": today_total,
            "month_kes": month_total,
        },
        "recent_payments": recent_payments.data,
        "security_alerts": alerts.data,
        "notifications": notifs.data,
        "package_popularity": [{"name": k, "sales": v} for k, v in popular],
    }


@router.get("/revenue")
async def revenue_summary(admin=Depends(require_admin)):
    db = get_db()
    result = db.table("revenue_summary").select("*").execute()
    return result.data


@router.get("/security")
async def security_events(resolved: bool = False, admin=Depends(require_admin)):
    db = get_db()
    result = db.table("security_events").select("*").eq(
        "is_resolved", resolved
    ).order("created_at", desc=True).limit(100).execute()
    return result.data


@router.get("/audit")
async def audit_logs(limit: int = 100, admin=Depends(require_admin)):
    db = get_db()
    result = db.table("audit_logs").select("*").order("created_at", desc=True).limit(limit).execute()
    return result.data
