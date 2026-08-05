# =============================================================================
# VIDATECH WIFI — General Utility Helpers
# backend/utils/helpers.py
# =============================================================================

import hashlib
import re
import uuid
from datetime import datetime, timezone
from typing import Optional


# ---------------------------------------------------------------------------
# Time
# ---------------------------------------------------------------------------

def utcnow() -> datetime:
    """Always use this instead of datetime.utcnow() — returns timezone-aware UTC."""
    return datetime.now(timezone.utc)


def hours_from_now(hours: int) -> datetime:
    """Returns a timezone-aware UTC datetime N hours from now."""
    from datetime import timedelta
    return utcnow() + timedelta(hours=hours)


# ---------------------------------------------------------------------------
# Phone number normalisation (Kenyan numbers)
# ---------------------------------------------------------------------------

def normalise_phone(phone: str) -> Optional[str]:
    """
    Accepts:
        0712345678
        +254712345678
        254712345678
        712345678

    Returns:
        2547XXXXXXXX  (Daraja-compatible format)
        None if the number is invalid
    """
    phone = re.sub(r"\s+", "", phone)  # strip whitespace

    if phone.startswith("+254"):
        phone = phone[1:]              # remove leading +
    elif phone.startswith("0"):
        phone = "254" + phone[1:]
    elif phone.startswith("7") or phone.startswith("1"):
        phone = "254" + phone

    if re.fullmatch(r"254[71]\d{8}", phone):
        return phone

    return None


def is_valid_phone(phone: str) -> bool:
    return normalise_phone(phone) is not None


# ---------------------------------------------------------------------------
# MAC address
# ---------------------------------------------------------------------------

def normalise_mac(mac: str) -> Optional[str]:
    """
    Normalises a MAC address to lowercase colon-separated format.
    aa:bb:cc:dd:ee:ff
    Returns None if invalid.
    """
    mac = mac.strip().lower()
    mac = re.sub(r"[-.]", ":", mac)   # handle dashes and dots
    parts = mac.split(":")

    if len(parts) != 6:
        return None

    for part in parts:
        if not re.fullmatch(r"[0-9a-f]{2}", part):
            return None

    return ":".join(parts)


def is_valid_mac(mac: str) -> bool:
    return normalise_mac(mac) is not None


# ---------------------------------------------------------------------------
# Password hashing (bcrypt via passlib — never store plain passwords)
# ---------------------------------------------------------------------------

def hash_password(plain: str) -> str:
    from passlib.context import CryptContext
    ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
    return ctx.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    from passlib.context import CryptContext
    ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
    return ctx.verify(plain, hashed)


# ---------------------------------------------------------------------------
# UUID
# ---------------------------------------------------------------------------

def new_uuid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Data sanitisation
# ---------------------------------------------------------------------------

def sanitise_string(value: str, max_length: int = 255) -> str:
    """Strip leading/trailing whitespace and truncate."""
    return value.strip()[:max_length]


def mask_phone(phone: str) -> str:
    """Returns 07*****678 — safe for logs and UI display."""
    if len(phone) < 6:
        return "***"
    return phone[:2] + "*" * (len(phone) - 5) + phone[-3:]


def mask_mac(mac: str) -> str:
    """Returns aa:bb:cc:**:**:** — safe for logs."""
    parts = mac.split(":")
    if len(parts) != 6:
        return "**:**:**:**:**:**"
    return ":".join(parts[:3] + ["**", "**", "**"])
