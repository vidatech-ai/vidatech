# =============================================================================
# VIDATECH WIFI — Audit Logging
# backend/security/audit.py
# =============================================================================

import logging
from typing import Optional
from db import get_db

logger = logging.getLogger("vidatech.audit")


async def log_event(
    action: str,
    description: str,
    actor_id: Optional[str] = None,
    actor_role: Optional[str] = None,
    target_table: Optional[str] = None,
    target_id: Optional[str] = None,
    old_value: Optional[dict] = None,
    new_value: Optional[dict] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> None:
    """
    Write an immutable audit log entry.
    Call this for every state-changing admin or system action.
    Audit rows cannot be updated or deleted (enforced at DB level).
    """
    try:
        db = get_db()
        db.table("audit_logs").insert({
            "actor_id": actor_id,
            "actor_role": actor_role,
            "action": action,
            "target_table": target_table,
            "target_id": target_id,
            "description": description,
            "old_value": old_value,
            "new_value": new_value,
            "ip_address": ip_address,
            "user_agent": user_agent,
        }).execute()
    except Exception as e:
        # Never let audit failure crash the main request
        logger.error(f"Audit log write failed: {e}")


async def log_security_event(
    event_type: str,
    description: str,
    severity: str = "warning",
    user_id: Optional[str] = None,
    device_id: Optional[str] = None,
    source_ip: Optional[str] = None,
    source_mac: Optional[str] = None,
    metadata: Optional[dict] = None,
    location_id: Optional[str] = None,
) -> None:
    """
    Write a security event.
    Triggers admin notification for critical severity.
    """
    try:
        db = get_db()
        result = db.table("security_events").insert({
            "event_type": event_type,
            "description": description,
            "severity": severity,
            "user_id": user_id,
            "device_id": device_id,
            "source_ip": source_ip,
            "source_mac": source_mac,
            "metadata": metadata or {},
            "location_id": location_id,
        }).execute()

        if severity == "critical":
            db.table("notifications").insert({
                "title": f"Security Alert: {event_type.replace('_', ' ').title()}",
                "body": description,
                "type": "security",
                "metadata": {"event_id": result.data[0]["id"]},
            }).execute()

        logger.warning(f"Security event [{severity}] {event_type}: {description}")

    except Exception as e:
        logger.error(f"Security event write failed: {e}")
