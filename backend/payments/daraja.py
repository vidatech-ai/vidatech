# =============================================================================
# VIDATECH WIFI — Daraja STK Push
# backend/payments/daraja.py
# =============================================================================

import base64
import logging
from datetime import datetime

import httpx

from config import get_settings

logger = logging.getLogger("vidatech.daraja")
settings = get_settings()


def _get_timestamp() -> str:
    return datetime.now().strftime("%Y%m%d%H%M%S")


def _get_password(timestamp: str) -> str:
    raw = f"{settings.DARAJA_SHORTCODE}{settings.DARAJA_PASSKEY}{timestamp}"
    return base64.b64encode(raw.encode()).decode()


async def _get_access_token() -> str:
    credentials = base64.b64encode(
        f"{settings.DARAJA_CONSUMER_KEY}:{settings.DARAJA_CONSUMER_SECRET}".encode()
    ).decode()

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{settings.DARAJA_BASE_URL}/oauth/v1/generate?grant_type=client_credentials",
            headers={"Authorization": f"Basic {credentials}"},
            timeout=15,
        )
        response.raise_for_status()
        return response.json()["access_token"]


async def initiate_stk_push(
    phone: str,
    amount: int,
    account_ref: str,
    description: str,
) -> str:
    """
    Initiates an M-Pesa STK push.
    Returns the CheckoutRequestID for tracking.
    """
    token     = await _get_access_token()
    timestamp = _get_timestamp()
    password  = _get_password(timestamp)

    payload = {
        "BusinessShortCode": settings.DARAJA_SHORTCODE,
        "Password": password,
        "Timestamp": timestamp,
        "TransactionType": "CustomerBuyGoodsOnline",
        "Amount": amount,
        "PartyA": phone,
        "PartyB": settings.DARAJA_TILL_NUMBER,
        "PhoneNumber": phone,
        "CallBackURL": settings.DARAJA_CALLBACK_URL,
        "AccountReference": account_ref,
        "TransactionDesc": description,
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{settings.DARAJA_BASE_URL}/mpesa/stkpush/v1/processrequest",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()

    if data.get("ResponseCode") != "0":
        raise Exception(f"Daraja error: {data.get('ResponseDescription', 'Unknown error')}")

    logger.info(f"STK push initiated: {data['CheckoutRequestID']} → {phone}")
    return data["CheckoutRequestID"]
