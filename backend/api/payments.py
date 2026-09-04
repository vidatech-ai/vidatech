# =============================================================================
# VIDATECH WIFI — Payments API
# backend/api/payments.py
# =============================================================================

import logging
from fastapi import APIRouter, HTTPException, Request, status, Depends
from pydantic import BaseModel
from typing import Optional

from auth.dependencies import require_admin
from db import get_db
from utils import normalise_phone, utcnow, hours_from_now
from payments.paystack import initiate_stk_push, verify_webhook_signature, PaystackError

logger = logging.getLogger("vidatech.payments")
router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class PaymentInitiate(BaseModel):
    phone: str
    package_id: str
    mac_address: Optional[str] = None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/initiate", status_code=status.HTTP_202_ACCEPTED)
async def initiate_payment(body: PaymentInitiate, request: Request):
    """
    Customer initiates payment.
    Triggers M-Pesa STK push to their phone via Paystack.
    """
    db = get_db()

    phone = normalise_phone(body.phone)
    if not phone:
        raise HTTPException(status_code=400, detail="Invalid phone number.")

    # Fetch package
    pkg_result = db.table("packages").select("*").eq("id", body.package_id).eq("status", "active").single().execute()
    if not pkg_result.data:
        raise HTTPException(status_code=404, detail="Package not found or inactive.")

    package = pkg_result.data

    # Detect MAC from IP if not provided
    client_ip = (
        request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        or request.client.host
    )
    mac_address = body.mac_address
    if not mac_address or mac_address == "00:00:00:00:00:00":
        # Try DB first
        device_result = db.table("devices").select("mac_address").eq("ip_address", client_ip).limit(1).execute()
        if device_result.data and device_result.data[0]["mac_address"] not in (None, "00:00:00:00:00:00"):
            mac_address = device_result.data[0]["mac_address"]
        else:
            # Ask router directly via ARP lookup
            try:
                import httpx
                async with httpx.AsyncClient() as hclient:
                    r = await hclient.get(
                        "http://192.168.2.1/cgi-bin/getmac_by_ip",
                        params={"ip": client_ip, "token": "vidatech2026secret"},
                        timeout=3,
                    )
                    rdata = r.json()
                    mac_address = rdata.get("mac") or "00:00:00:00:00:00"
            except Exception:
                mac_address = "00:00:00:00:00:00"

    # Create pending payment record
    payment_result = db.table("payments").insert({
        "phone": phone,
        "package_id": package["id"],
        "amount_kes": package["price_kes"],
        "mac_address": mac_address.lower(),
        "status": "pending",
        "ip_address": client_ip,
    }).execute()

    payment = payment_result.data[0]

    # Initiate STK push via Paystack
    try:
        reference = await initiate_stk_push(
            phone=phone,
            amount=int(package["price_kes"]),
            account_ref=f"VIDATECH-{payment['id'][:8].upper()}",
            description=f"{package['name']} - Vidatech WiFi",
        )
    except PaystackError as e:
        logger.error(f"STK push rejected by Paystack: {e}")
        db.table("payments").update({
            "status": "failed",
            "failure_reason": str(e),
        }).eq("id", payment["id"]).execute()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"STK push failed unexpectedly: {e}")
        db.table("payments").update({
            "status": "failed",
            "failure_reason": str(e),
        }).eq("id", payment["id"]).execute()
        raise HTTPException(status_code=502, detail="Payment initiation failed. Please try again.")

    # Save Paystack reference (replaces mpesa_checkout_id)
    db.table("payments").update({
        "mpesa_checkout_id": reference,       # reusing existing column — rename later if desired
    }).eq("id", payment["id"]).execute()

    # Update device record
    if mac_address and mac_address != "00:00:00:00:00:00":
        db.table("devices").upsert({
            "mac_address": mac_address.lower(),
            "ip_address": client_ip,
            "status": "unknown",
        }, on_conflict="mac_address").execute()

    logger.info(f"STK push sent to {phone} for package '{package['name']}'")

    return {
        "message": "Payment prompt sent to your phone. Enter your M-Pesa PIN.",
        "payment_id": payment["id"],
        "reference": reference,
        "amount": package["price_kes"],
        "package": package["name"],
    }


@router.post("/webhook")
async def paystack_webhook(request: Request):
    """
    Paystack posts to this endpoint after payment completes or fails.
    URL: https://vidatech-wifi.onrender.com/payments/webhook
    """
    db = get_db()

    raw_body = await request.body()
    signature = request.headers.get("x-paystack-signature", "")

    if not verify_webhook_signature(raw_body, signature):
        logger.warning("Paystack webhook signature verification failed.")
        raise HTTPException(status_code=401, detail="Invalid signature.")

    body = await request.json() if not raw_body else __import__("json").loads(raw_body)
    event = body.get("event")
    data  = body.get("data", {})

    # Only handle charge events
    if event not in ("charge.success", "charge.failed"):
        return {"status": "ignored"}

    reference = data.get("reference")
    if not reference:
        logger.error("Paystack webhook missing reference.")
        return {"status": "ignored"}

    # Find payment record
    pay_result = db.table("payments").select("*, packages(*)").eq("mpesa_checkout_id", reference).single().execute()
    if not pay_result.data:
        logger.warning(f"Webhook for unknown reference: {reference}")
        return {"status": "ignored"}

    payment = pay_result.data
    package = payment["packages"]

    if event == "charge.failed":
        db.table("payments").update({
            "status": "failed",
            "failure_reason": data.get("gateway_response", "Payment failed"),
        }).eq("id", payment["id"]).execute()
        logger.warning(f"Payment failed for {payment['phone']}: {data.get('gateway_response')}")
        return {"status": "ok"}

    # charge.success
    txn_code    = data.get("id") or reference
    amount_kes  = int(data.get("amount", 0)) // 100     # convert back from kobo

    db.table("payments").update({
        "status": "confirmed",
        "mpesa_transaction_code": str(txn_code),
        "confirmed_at": utcnow().isoformat(),
    }).eq("id", payment["id"]).execute()

    mac_address = payment.get("mac_address", "00:00:00:00:00:00")
    if not mac_address or mac_address == "00:00:00:00:00:00":
        ip_lookup = db.table("devices").select("mac_address").eq(
            "ip_address", payment.get("ip_address")
        ).limit(1).execute()
        if ip_lookup.data:
            mac_address = ip_lookup.data[0]["mac_address"]

    # MAC spoofing check
    existing = db.table("sessions").select("id, ip_address").eq(
        "mac_address", mac_address
    ).eq("status", "active").execute()

    if existing.data:
        for s in existing.data:
            if s.get("ip_address") and s["ip_address"] != payment.get("ip_address"):
                db.table("security_events").insert({
                    "event_type": "mac_spoofing",
                    "severity": "critical",
                    "description": f"MAC {mac_address} seen from multiple IPs — possible spoofing.",
                    "source_ip": payment.get("ip_address"),
                    "metadata": {"mac": mac_address, "payment_id": payment["id"]},
                }).execute()
                logger.warning(f"MAC spoofing detected: {mac_address}")

    # Get device
    device_result = db.table("devices").select("*").eq("mac_address", mac_address).limit(1).execute()
    device = device_result.data[0] if device_result.data else None

    # Create session — use null MAC if unknown so reconnect-by-phone can assign it
    clean_mac = mac_address if mac_address and mac_address != "00:00:00:00:00:00" else None
    session_result = db.table("sessions").insert({
        "payment_id": payment["id"],
        "package_id": package["id"],
        "mac_address": clean_mac,
        "ip_address": device["ip_address"] if device else None,
        "phone": payment["phone"],
        "status": "active",
        "started_at": utcnow().isoformat(),
        "expires_at": hours_from_now(package["duration_hours"]).isoformat(),
    }).execute()
    session = session_result.data[0]

    # Mark device allowed
    if device:
        db.table("devices").update({"status": "allowed"}).eq("id", device["id"]).execute()

    # Instantly grant internet on router — don't wait for agent 30s cycle
    if clean_mac:
        import httpx
        try:
            async with httpx.AsyncClient() as hclient:
                await hclient.get(
                    "http://192.168.2.1/cgi-bin/vidatech_auth",
                    params={"mac": clean_mac, "token": "vidatech2026secret"},
                    timeout=3,
                )
            logger.info(f"Instant grant sent to router for {clean_mac}")
        except Exception as e:
            logger.warning(f"Instant grant failed (agent will sync): {e}")

    # Notify admin
    db.table("notifications").insert({
        "title": "New Payment Received",
        "body": f"KES {amount_kes} from {payment['phone']} for {package['name']}. Ref: {txn_code}",
        "type": "payment",
        "metadata": {"payment_id": payment["id"], "session_id": session["id"]},
    }).execute()

    logger.info(f"Payment confirmed: {txn_code} | {payment['phone']} | {package['name']}")
    return {"status": "ok"}


@router.get("/")
async def list_payments(limit: int = 50, admin=Depends(require_admin)):
    db = get_db()
    result = db.table("payments").select("*, packages(name)").order("created_at", desc=True).limit(limit).execute()
    return result.data


@router.get("/status/latest")
async def latest_payment_status(phone: str):
    """Poll latest payment by phone number — used when payment_id is unavailable due to fetch timeout."""
    db = get_db()
    phone = normalise_phone(phone)
    if not phone:
        raise HTTPException(status_code=400, detail="Invalid phone.")
    result = db.table("payments").select(
        "id, status, mpesa_transaction_code, confirmed_at"
    ).eq("phone", phone).order("created_at", desc=True).limit(1).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="No payment found.")
    return result.data[0]


@router.get("/status/{payment_id}")
async def payment_status(payment_id: str):
    """Customer polls this to know if their payment went through."""
    db = get_db()
    result = db.table("payments").select("id, status, mpesa_transaction_code, confirmed_at").eq("id", payment_id).single().execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Payment not found.")
    return result.data