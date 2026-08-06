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
from payments.daraja import initiate_stk_push

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
    Triggers M-Pesa STK push to their phone.
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

    ## Detect MAC from IP if not provided
    client_ip = request.client.host
    mac_address = body.mac_address
    if not mac_address or mac_address == "00:00:00:00:00:00":
        device_result = db.table("devices").select("mac_address").eq("ip_address", client_ip).limit(1).execute()
        if device_result.data:
            mac_address = device_result.data[0]["mac_address"]
        else:
            mac_address = "00:00:00:00:00:00"

    # Create pending payment record
    payment_result = db.table("payments").insert({
        "phone": phone,
        "package_id": package["id"],
        "amount_kes": package["price_kes"],
        "mac_address": mac_address.lower(),
        "status": "pending",
    }).execute()

    payment = payment_result.data[0]

    # Initiate STK push
    try:
        checkout_id = await initiate_stk_push(
            phone=phone,
            amount=int(package["price_kes"]),
            account_ref=f"VIDATECH-{payment['id'][:8].upper()}",
            description=f"{package['name']} - Vidatech WiFi",
        )
    except Exception as e:
        logger.error(f"STK push failed: {e}")
        db.table("payments").update({
            "status": "failed",
            "failure_reason": str(e),
        }).eq("id", payment["id"]).execute()
        raise HTTPException(status_code=502, detail="Payment initiation failed. Please try again.")

    # Save checkout ID
    db.table("payments").update({
        "mpesa_checkout_id": checkout_id,
    }).eq("id", payment["id"]).execute()

    # Update device record with current IP
    if mac_address and mac_address != "00:00:00:00:00:00":
        db.table("devices").upsert({
            "mac_address": mac_address.lower(),
            "ip_address": client_ip,
            "status": "pending_payment",
        }, on_conflict="mac_address").execute()

    logger.info(f"STK push sent to {phone} for package '{package['name']}'")

    return {
        "message": "Payment prompt sent to your phone. Enter your M-Pesa PIN.",
        "payment_id": payment["id"],
        "checkout_id": checkout_id,
        "amount": package["price_kes"],
        "package": package["name"],
    }


@router.post("/callback")
async def daraja_callback(request: Request):
    """
    Safaricom Daraja calls this endpoint after payment completes or fails.
    This URL must be publicly accessible (your Render URL).
    """
    db = get_db()
    body = await request.json()

    try:
        stk = body["Body"]["stkCallback"]
        checkout_id   = stk["CheckoutRequestID"]
        result_code   = stk["ResultCode"]
        result_desc   = stk["ResultDesc"]
    except (KeyError, TypeError):
        logger.error(f"Malformed Daraja callback: {body}")
        return {"ResultCode": 0, "ResultDesc": "Accepted"}

    # Find payment record
    pay_result = db.table("payments").select("*, packages(*)").eq("mpesa_checkout_id", checkout_id).single().execute()

    if not pay_result.data:
        logger.warning(f"Callback for unknown checkout_id: {checkout_id}")
        return {"ResultCode": 0, "ResultDesc": "Accepted"}

    payment = pay_result.data
    package = payment["packages"]

    if result_code != 0:
        # Payment failed
        db.table("payments").update({
            "status": "failed",
            "failure_reason": result_desc,
        }).eq("id", payment["id"]).execute()

        logger.warning(f"Payment failed for {payment['phone']}: {result_desc}")
        return {"ResultCode": 0, "ResultDesc": "Accepted"}

    # Payment successful — extract transaction code
    items = {i["Name"]: i["Value"] for i in stk.get("CallbackMetadata", {}).get("Item", [])}
    txn_code = items.get("MpesaReceiptNumber")
    amount   = items.get("Amount")

    db.table("payments").update({
        "status": "confirmed",
        "mpesa_transaction_code": txn_code,
        "confirmed_at": utcnow().isoformat(),
    }).eq("id", payment["id"]).execute()

    # Get MAC from payment record
    mac_address = payment.get("mac_address", "00:00:00:00:00:00")

    # Check for MAC spoofing — if another device is already using this MAC flag it
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

    # Get device record
    device_result = db.table("devices").select("*").eq("mac_address", mac_address).limit(1).execute()
    device = device_result.data[0] if device_result.data else None

    # Create session
    session_data = {
        "payment_id": payment["id"],
        "package_id": package["id"],
        "mac_address": mac_address,
        "ip_address": device["ip_address"] if device else None,
        "status": "active",
        "started_at": utcnow().isoformat(),
        "expires_at": hours_from_now(package["duration_hours"]).isoformat(),
    }

    session_result = db.table("sessions").insert(session_data).execute()
    session = session_result.data[0]

    # Mark device as allowed
    if device:
        db.table("devices").update({"status": "allowed"}).eq("id", device["id"]).execute()

    # Notify admin
    db.table("notifications").insert({
        "title": "New Payment Received",
        "body": f"KES {amount} from {payment['phone']} for {package['name']}. Receipt: {txn_code}",
        "type": "payment",
        "metadata": {"payment_id": payment["id"], "session_id": session["id"]},
    }).execute()

    logger.info(f"Payment confirmed: {txn_code} | {payment['phone']} | {package['name']}")
    return {"ResultCode": 0, "ResultDesc": "Accepted"}


@router.get("/")
async def list_payments(limit: int = 50, admin=Depends(require_admin)):
    db = get_db()
    result = db.table("payments").select("*, packages(name)").order("created_at", desc=True).limit(limit).execute()
    return result.data


@router.get("/status/{payment_id}")
async def payment_status(payment_id: str):
    """Customer polls this to know if their payment went through."""
    db = get_db()
    result = db.table("payments").select("id, status, mpesa_transaction_code, confirmed_at").eq("id", payment_id).single().execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Payment not found.")
    return result.data
