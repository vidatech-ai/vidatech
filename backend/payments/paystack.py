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


class PaystackError(Exception):
    """Raised when Paystack rejects or fails to process a charge."""
    pass


def _to_paystack_phone(phone: str) -> str:
    """Paystack Mobile Money expects +2547XXXXXXXX format."""
    if not phone.startswith("+"):
        return "+" + phone
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
        "email": f"customer+{phone}@vidatech-wifi.com",           # Paystack requires valid email; phone-based placeholder
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
        try:
            response = await client.post(
                f"{PAYSTACK_BASE_URL}/charge",
                json=payload,
                headers={
                    "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
                    "Content-Type": "application/json",
                },
                timeout=30,
            )
        except httpx.TimeoutException:
            logger.error("Paystack request timed out")
            raise PaystackError("Payment request timed out. Please try again.")
        except httpx.RequestError as e:
            logger.error(f"Paystack network error: {e}")
            raise PaystackError("Could not reach payment provider. Please try again.")

        if response.status_code >= 400:
            logger.error(f"Paystack raw error: {response.text}")
            try:
                err_body = response.json()
            except ValueError:
                err_body = {}
            friendly = err_body.get("data", {}).get("message") or err_body.get("message") or "Payment could not be processed."
            raise PaystackError(friendly)

        data = response.json()

    if not data.get("status"):
        friendly = data.get("message", "Payment could not be processed.")
        logger.error(f"Paystack error: {friendly} | full response: {data}")
        raise PaystackError(friendly)

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