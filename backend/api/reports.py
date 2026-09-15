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

@router.get("/analytics")
async def analytics(admin=Depends(require_admin)):
    db = get_db()
    # Total devices
    total_devices = db.table("devices").select("id", count="exact").execute()
    # Top customer by payment count
    payments_all = db.table("payments").select("phone, amount_kes").eq("status", "confirmed").execute()
    customer_count = {}
    customer_spend = {}
    for p in payments_all.data:
        ph = p["phone"]
        customer_count[ph] = customer_count.get(ph, 0) + 1
        customer_spend[ph] = customer_spend.get(ph, 0) + p["amount_kes"]
    top_customer = max(customer_count, key=customer_count.get) if customer_count else None
    # Peak hour
    confirmed = db.table("payments").select("confirmed_at").eq("status", "confirmed").execute()
    hour_count = {}
    for p in confirmed.data:
        if p["confirmed_at"]:
            h = int(p["confirmed_at"][11:13])
            hour_count[h] = hour_count.get(h, 0) + 1
    peak_hour = max(hour_count, key=hour_count.get) if hour_count else None
    # Daily revenue last 30 days
    import datetime
    days = []
    for i in range(29, -1, -1):
        d = (datetime.datetime.utcnow() - datetime.timedelta(days=i)).date().isoformat()
        days.append(d)
    daily = db.table("payments").select("amount_kes, confirmed_at").eq("status", "confirmed").gte("confirmed_at", days[0]).execute()
    daily_map = {d: 0 for d in days}
    for p in daily.data:
        if p["confirmed_at"]:
            d = p["confirmed_at"][:10]
            if d in daily_map:
                daily_map[d] += p["amount_kes"]
    # Package popularity
    pkg_sales = db.table("payments").select("packages(name), amount_kes").eq("status", "confirmed").execute()
    pkg_count = {}
    for p in pkg_sales.data:
        name = p["packages"]["name"] if p["packages"] else "Unknown"
        pkg_count[name] = pkg_count.get(name, 0) + 1
    return {
        "total_devices": total_devices.count,
        "top_customer": top_customer,
        "top_customer_payments": customer_count.get(top_customer, 0) if top_customer else 0,
        "top_customer_spend": customer_spend.get(top_customer, 0) if top_customer else 0,
        "peak_hour": peak_hour,
        "hour_distribution": hour_count,
        "daily_revenue": [{"date": d, "kes": daily_map[d]} for d in days],
        "package_popularity": [{"name": k, "sales": v} for k, v in sorted(pkg_count.items(), key=lambda x: x[1], reverse=True)],
    }


@router.get("/top-customer-public")
async def top_customer_public():
    """Public endpoint — returns masked top customer info for portal display."""
    db = get_db()
    import datetime
    EXCLUDED = {"254113259315", "0113259315"}
    month_start = datetime.datetime.utcnow().replace(day=1).date().isoformat()
    payments = db.table("payments").select("phone, amount_kes").eq("status", "confirmed").gte("confirmed_at", month_start).execute()
    customer_count = {}
    customer_spend = {}
    for p in payments.data:
        ph = p["phone"]
        if ph in EXCLUDED:
            continue
        customer_count[ph] = customer_count.get(ph, 0) + 1
        customer_spend[ph] = customer_spend.get(ph, 0) + p["amount_kes"]
    if not customer_count:
        return {"phone": None, "payments": 0, "spend": 0}
    top = max(customer_count, key=customer_count.get)
    masked = top[:5] + "****" + top[-2:]
    return {
        "phone": masked,
        "payments": customer_count[top],
        "spend": customer_spend[top],
    }
