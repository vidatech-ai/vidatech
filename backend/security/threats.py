# =============================================================================
# VIDATECH WIFI — Threat Detection
# backend/security/threats.py
# =============================================================================

import logging
from typing import Optional
from db import get_db
from security.audit import log_security_event
from utils import utcnow

logger = logging.getLogger("vidatech.threats")


async def check_mac_change(user_id: str, new_mac: str) -> bool:
    """
    Detects if a user is connecting from a MAC address
    that doesn't match their registered devices.
    Returns True if suspicious.
    """
    db = get_db()
    result = db.table("users").select("mac_addresses").eq("id", user_id).single().execute()

    if not result.data:
        return False

    known_macs = result.data.get("mac_addresses", [])

    if known_macs and new_mac not in known_macs:
        await log_security_event(
            event_type="mac_change",
            description=f"User connected from unrecognised MAC {new_mac}. Known: {known_macs}",
            severity="warning",
            user_id=user_id,
            source_mac=new_mac,
        )
        return True

    return False


async def check_session_hijack(session_id: str, current_ip: str, current_mac: str) -> bool:
    """
    Detects if a session is being used from a different IP or MAC
    than when it was created — potential session hijacking.
    Returns True if suspicious.
    """
    db = get_db()
    result = db.table("sessions").select("ip_address, mac_address").eq("id", session_id).single().execute()

    if not result.data:
        return False

    session = result.data
    suspicious = False

    if session["mac_address"] and session["mac_address"] != current_mac:
        await log_security_event(
            event_type="session_hijack",
            description=f"Session {session_id} MAC mismatch. Original: {session['mac_address']} Current: {current_mac}",
            severity="critical",
            source_mac=current_mac,
        )
        suspicious = True

    if session["ip_address"] and session["ip_address"] != current_ip:
        await log_security_event(
            event_type="session_hijack",
            description=f"Session {session_id} IP mismatch. Original: {session['ip_address']} Current: {current_ip}",
            severity="warning",
            source_ip=current_ip,
        )
        suspicious = True

    return suspicious


async def check_unknown_device(mac: str, ip: str) -> None:
    """
    Flags a device that has never been seen before.
    """
    db = get_db()
    result = db.table("devices").select("id, status").eq("mac_address", mac).execute()

    if not result.data:
        await log_security_event(
            event_type="unknown_device",
            description=f"Unknown device connected: MAC {mac} IP {ip}",
            severity="info",
            source_mac=mac,
            source_ip=ip,
        )


async def check_blocked_device(mac: str) -> bool:
    """
    Returns True if the device MAC is on the blocklist.
    """
    db = get_db()
    result = db.table("devices").select("status").eq("mac_address", mac).single().execute()

    if result.data and result.data["status"] == "blocked":
        await log_security_event(
            event_type="blocked_device_attempt",
            description=f"Blocked device attempted to connect: {mac}",
            severity="critical",
            source_mac=mac,
        )
        return True

    return False


async def expire_sessions() -> int:
    """
    Background task: finds all sessions past their expiry and marks them expired.
    Also blocks devices whose sessions have expired.
    Returns count of expired sessions.
    """
    db = get_db()
    now = utcnow().isoformat()

    result = db.table("sessions").update({
        "status": "expired",
        "terminated_at": now,
        "termination_reason": "expired",
    }).eq("status", "active").lt("expires_at", now).execute()

    count = len(result.data) if result.data else 0

    if count > 0:
        logger.info(f"Expired {count} session(s).")

    return count
