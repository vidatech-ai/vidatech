# =============================================================================
# VIDATECH WIFI — Paystack Mobile Money (STK Push)
# backend/payments/paystack.py
# =============================================================================

import hashlib
import hmac
import logging

import httpx

from config import get_settings

logger = logging.getLogger("vidatech.paystack")
settings = get_settings()

PAYSTACK_BASE_URL = "https://api.paystack.co"


def _to_paystack_phone(phone: str) -> str:
    """Paystack Mobile Money expects 2547XXXXXXXX — already what normalise_phone returns."""
    return phone


async def initiate_stk_push(
    phone: str,
    amount: int,
    account_ref: str,
    description: str,
) -> str:
    """
    Initiates a Paystack Mobile Money (M-Pesa) charge — triggers STK push.
    Returns the Paystack transaction reference for tracking.
    """
    # Paystack expects amount in kobo/cents — KES uses integer shillings so multiply by 100
    payload = {
        "amount": str(amount * 100),
        "email": f"{phone}@vidatech.wifi",          # Paystack requires email; phone-based placeholder
        "currency": "KES",
        "mobile_money": {
            "phone": _to_paystack_phone(phone),
            "provider": "mpesa",
        },
        "reference": account_ref,
        "metadata": {
            "description": description,
            "cancel_action": "https://vidatech-wifi.onrender.com/payments/cancelled",
        },
    }

    logger.info(f"Paystack charge payload: {payload}")
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{PAYSTACK_BASE_URL}/charge",
            json=payload,
            headers={
                "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
                "Content-Type": "application/json",
            },
            timeout=30,
        )
        if response.status_code >= 400:
            logger.error(f"Paystack raw error: {response.text}")
        response.raise_for_status()
        data = response.json()

    if not data.get("status"):
        raise Exception(f"Paystack error: {data.get('message', 'Unknown error')} | full response: {data}")

    reference = data["data"]["reference"]
    logger.info(f"STK push initiated: {reference} → {phone}")
    return reference


def verify_webhook_signature(payload: bytes, signature: str) -> bool:
    """
    Verifies that a webhook request genuinely came from Paystack.
    Paystack signs the raw body with HMAC-SHA512 using your secret key.
    """
    expected = hmac.new(
        settings.PAYSTACK_SECRET_KEY.encode(),
        payload,
        hashlib.sha512,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)