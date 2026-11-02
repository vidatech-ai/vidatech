# =============================================================================
# VIDATECH WIFI — Vouchers API
# backend/api/vouchers.py
# =============================================================================
import logging
import re
import secrets
import uuid
import datetime
from datetime import timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from auth.dependencies import require_admin
from db import get_db
from utils.helpers import normalise_phone, normalise_mac

logger = logging.getLogger("vidatech.vouchers")
router = APIRouter()

ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"      # no 0 O 1 I L
CODE_RE = re.compile(r"^[A-HJKMNP-Z2-9]{8}$")
INVALID_MSG = "Invalid voucher or phone number."

FAIL_LIMIT_PHONE = 5      # failed attempts per phone in WINDOW
FAIL_LIMIT_MAC = 8        # failed attempts per device in WINDOW
FAIL_LIMIT_GLOBAL = 200   # failed attempts overall in GLOBAL_WINDOW
WINDOW_MIN = 15
GLOBAL_WINDOW_MIN = 5
SLOT_STALE_MIN = 10       # a device unseen this long can lose its voucher slot


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------
def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _parse(value) -> Optional[datetime.datetime]:
    """Parse a Postgres/ISO timestamp safely on any Python 3 version."""
    if not value:
        return None
    s = str(value).strip().replace("Z", "+00:00").replace(" ", "T", 1)
    m = re.match(r"^(.*?)(\.\d+)?([+-]\d\d:\d\d)?$", s)
    if not m:
        return None
    base, frac, tz = m.groups()
    frac = (frac or ".0")[:7].ljust(7, "0")
    try:
        return datetime.datetime.fromisoformat(base + frac + (tz or "+00:00"))
    except ValueError:
        return None


def _new_code() -> str:
    raw = "".join(secrets.choice(ALPHABET) for _ in range(8))
    return raw[:4] + "-" + raw[4:]


def _fmt_code(raw: str) -> Optional[str]:
    cleaned = re.sub(r"[^A-Za-z0-9]", "", raw or "").upper()
    if not CODE_RE.match(cleaned):
        return None
    return cleaned[:4] + "-" + cleaned[4:]


def _display_status(v: dict, now: datetime.datetime) -> str:
    st = v.get("status")
    if st == "revoked":
        return "revoked"
    if st == "active":
        exp = _parse(v.get("expires_at"))
        return "expired" if (exp is None or exp <= now) else "active"
    vu = _parse(v.get("valid_until"))
    return "expired" if (vu is not None and vu <= now) else "unused"


def _client_ip(request: Request) -> str:
    return (
        request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        or (request.client.host if request.client else "")
    )


def _fail(reason: str, message: str) -> dict:
    return {"allowed": False, "reason": reason, "message": message}


def _audit(db, admin, action: str, target_id, description: str):
    try:
        db.table("audit_logs").insert({
            "actor_id": admin["sub"],
            "actor_role": admin["role"],
            "action": action,
            "target_table": "vouchers",
            "target_id": str(target_id),
            "description": description,
        }).execute()
    except Exception as e:
        logger.warning(f"voucher audit log failed: {e}")


def _log_attempt(db, phone, mac, ip, success: bool):
    try:
        db.table("voucher_attempts").insert({
            "phone": phone, "mac_address": mac, "ip_address": ip, "success": success,
        }).execute()
    except Exception as e:
        logger.warning(f"voucher attempt log failed: {e}")


def _resolve_mac(db, body_mac, ip) -> Optional[str]:
    """MAC sent by the portal first; fall back to the devices table by IP."""
    if body_mac:
        try:
            mac = normalise_mac(body_mac)
        except Exception:
            mac = None
        if mac and mac != "00:00:00:00:00:00":
            return mac.lower()
    if ip:
        res = db.table("devices").select("mac_address").eq("ip_address", ip).limit(1).execute()
        if res.data and res.data[0].get("mac_address") not in (None, "00:00:00:00:00:00"):
            return res.data[0]["mac_address"].lower()
    return None


def _throttled(db, phone, mac, now) -> bool:
    since = (now - timedelta(minutes=WINDOW_MIN)).isoformat()
    gsince = (now - timedelta(minutes=GLOBAL_WINDOW_MIN)).isoformat()

    def cnt(q):
        return q.limit(1).execute().count or 0

    base = lambda: db.table("voucher_attempts").select("id", count="exact").eq("success", False)
    if cnt(base().eq("phone", phone).gte("created_at", since)) >= FAIL_LIMIT_PHONE:
        return True
    if cnt(base().eq("mac_address", mac).gte("created_at", since)) >= FAIL_LIMIT_MAC:
        return True
    if cnt(base().gte("created_at", gsince)) >= FAIL_LIMIT_GLOBAL:
        return True
    return False


def _create_session(db, mac, phone, expires_iso) -> str:
    res = db.table("sessions").insert({
        "mac_address": mac,
        "phone": phone,
        "status": "active",
        "started_at": _now().isoformat(),
        "expires_at": expires_iso,
        "termination_reason": None,
    }).execute()
    if not res.data:
        raise RuntimeError("voucher session insert returned no data")
    return res.data[0]["id"]


def _terminate_session(db, session_id, reason, now):
    if not session_id:
        return
    db.table("sessions").update({
        "status": "terminated",
        "terminated_at": now.isoformat(),
        "termination_reason": reason,
    }).eq("id", session_id).eq("status", "active").execute()


def _session_is_live(db, session_id, now) -> bool:
    if not session_id:
        return False
    res = db.table("sessions").select("status,expires_at").eq("id", session_id).limit(1).execute()
    if not res.data:
        return False
    s = res.data[0]
    exp = _parse(s.get("expires_at"))
    return s.get("status") == "active" and exp is not None and exp > now


# ----------------------------------------------------------------------------
# Models
# ----------------------------------------------------------------------------
class VoucherGenerate(BaseModel):
    hours: float = Field(gt=0, le=8760)
    max_devices: int = Field(default=1, ge=1, le=20)
    valid_days: int = Field(default=30, ge=1, le=365)
    phones: List[str] = Field(default_factory=list)
    count: int = Field(default=1, ge=1, le=100)


class RedeemBody(BaseModel):
    phone: str
    code: str
    mac: Optional[str] = None


# ----------------------------------------------------------------------------
# Admin endpoints
# ----------------------------------------------------------------------------
@router.post("/generate", status_code=201)
async def generate_vouchers(body: VoucherGenerate, admin=Depends(require_admin)):
    db = get_db()
    now = _now()

    phones, bad, seen = [], [], set()
    for p in body.phones:
        n = normalise_phone(p)
        if not n:
            bad.append(p)
        elif n not in seen:
            seen.add(n)
            phones.append(n)
    if bad:
        raise HTTPException(status_code=400, detail="Invalid phone number(s): " + ", ".join(bad))

    total = len(phones) if phones else body.count
    if total < 1 or total > 100:
        raise HTTPException(status_code=400, detail="You can generate 1 to 100 vouchers at a time.")

    duration_minutes = int(round(body.hours * 60))
    if duration_minutes < 1:
        raise HTTPException(status_code=400, detail="Duration is too short.")

    valid_until = (now + timedelta(days=body.valid_days)).isoformat()
    batch_id = str(uuid.uuid4())

    created = None
    for _attempt in range(5):
        codes = set()
        while len(codes) < total:
            codes.add(_new_code())
        codes = list(codes)
        rows = [{
            "code": codes[i],
            "duration_minutes": duration_minutes,
            "max_devices": body.max_devices,
            "locked_phone": phones[i] if phones else None,
            "valid_until": valid_until,
            "batch_id": batch_id,
            "created_by": str(admin.get("sub")),
        } for i in range(total)]
        try:
            res = db.table("vouchers").insert(rows).execute()
            if res.data and len(res.data) == total:
                created = res.data
                break
            logger.error("voucher batch insert returned unexpected row count")
        except Exception as e:
            logger.warning(f"voucher batch insert failed (attempt {_attempt + 1}): {e}")
    if not created:
        raise HTTPException(status_code=500, detail="Could not generate vouchers. Please try again.")

    _audit(db, admin, "voucher_generate", batch_id,
           f"Generated {total} voucher(s): {body.hours}h, {body.max_devices} device(s).")
    logger.info(f"Generated {total} vouchers in batch {batch_id}")
    return {
        "batch_id": batch_id,
        "vouchers": [{
            "id": r["id"], "code": r["code"], "locked_phone": r["locked_phone"],
            "hours": round(r["duration_minutes"] / 60, 2), "max_devices": r["max_devices"],
            "valid_until": r["valid_until"],
        } for r in created],
    }


@router.get("/phones")
async def known_phones(q: str = "", admin=Depends(require_admin)):
    """Numbers already in the system (recent payments and sessions) for the admin picker."""
    db = get_db()
    latest = {}
    for table in ("payments", "sessions"):
        rows = db.table(table).select("phone,created_at").order("created_at", desc=True).limit(1000).execute().data or []
        for r in rows:
            p = r.get("phone")
            if not p or not re.fullmatch(r"\+?\d{9,15}", p):
                continue
            t = r.get("created_at") or ""
            if p not in latest or t > latest[p]:
                latest[p] = t
    items = sorted(latest.items(), key=lambda kv: kv[1], reverse=True)
    digits = re.sub(r"\D", "", q or "")
    if digits:
        items = [kv for kv in items if digits in kv[0]]
    return {"phones": [{"phone": p, "last_activity": t} for p, t in items[:500]]}


@router.get("/")
async def list_vouchers(status: str = "all", limit: int = 300, admin=Depends(require_admin)):
    db = get_db()
    now = _now()
    limit = max(1, min(limit, 1000))
    rows = db.table("vouchers").select("*").order("created_at", desc=True).limit(limit).execute().data or []
    counts = {}
    ids = [r["id"] for r in rows]
    for i in range(0, len(ids), 100):
        for d in db.table("voucher_devices").select("voucher_id").in_("voucher_id", ids[i:i + 100]).execute().data or []:
            counts[d["voucher_id"]] = counts.get(d["voucher_id"], 0) + 1
    out = []
    for r in rows:
        st = _display_status(r, now)
        if status != "all" and st != status:
            continue
        out.append({
            "id": r["id"], "code": r["code"], "status": st,
            "hours": round(r["duration_minutes"] / 60, 2),
            "max_devices": r["max_devices"], "devices_used": counts.get(r["id"], 0),
            "locked_phone": r.get("locked_phone"), "redeemed_phone": r.get("redeemed_phone"),
            "redeemed_at": r.get("redeemed_at"), "expires_at": r.get("expires_at"),
            "valid_until": r.get("valid_until"), "created_at": r.get("created_at"),
            "batch_id": r.get("batch_id"),
        })
    return {"vouchers": out}


@router.post("/{voucher_id}/revoke")
async def revoke_voucher(voucher_id: str, admin=Depends(require_admin)):
    db = get_db()
    now = _now()
    res = db.table("vouchers").select("id,status,code").eq("id", voucher_id).limit(1).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Voucher not found.")
    v = res.data[0]
    db.table("vouchers").update({
        "status": "revoked", "revoked_at": now.isoformat(),
    }).eq("id", voucher_id).execute()
    rows = db.table("voucher_devices").select("session_id").eq("voucher_id", voucher_id).execute().data or []
    for r in rows:
        _terminate_session(db, r.get("session_id"), "voucher_revoked", now)
    _audit(db, admin, "voucher_revoke", voucher_id, f"Revoked voucher {v['code']}.")
    logger.info(f"Voucher {v['code']} revoked, {len(rows)} device(s) cut off")
    return {"message": f"Voucher {v['code']} revoked.", "devices_cut_off": len(rows)}


# ----------------------------------------------------------------------------
# Public endpoint — portal redemption
# ----------------------------------------------------------------------------
def _redeem(body: RedeemBody, request: Request) -> dict:
    db = get_db()
    now = _now()
    ip = _client_ip(request)

    phone = normalise_phone(body.phone)
    if not phone:
        return _fail("invalid_phone", "Enter a valid phone number.")

    mac = _resolve_mac(db, body.mac, ip)
    if not mac:
        return _fail("device_not_detected",
                     "We could not detect your device. Reconnect to the WiFi and try again.")

    if _throttled(db, phone, mac, now):
        return _fail("too_many_attempts",
                     "Too many failed attempts. Please wait 15 minutes and try again.")

    code = _fmt_code(body.code)
    if not code:
        _log_attempt(db, phone, mac, ip, False)
        return _fail("invalid_voucher", INVALID_MSG)

    found = db.table("vouchers").select("*").eq("code", code).limit(1).execute().data
    if not found:
        _log_attempt(db, phone, mac, ip, False)
        return _fail("invalid_voucher", INVALID_MSG)
    v = found[0]

    # The phone must match: the locked phone, or the phone that first redeemed it
    if v.get("locked_phone") and v["locked_phone"] != phone:
        _log_attempt(db, phone, mac, ip, False)
        return _fail("invalid_voucher", INVALID_MSG)
    if v["status"] == "active" and v.get("redeemed_phone") and v["redeemed_phone"] != phone:
        _log_attempt(db, phone, mac, ip, False)
        return _fail("invalid_voucher", INVALID_MSG)

    if v["status"] == "revoked":
        return _fail("voucher_unavailable", "This voucher is no longer valid.")

    if v["status"] == "unused":
        vu = _parse(v.get("valid_until"))
        if vu is not None and vu <= now:
            return _fail("voucher_expired", "This voucher has expired.")
        expires = now + timedelta(minutes=int(v["duration_minutes"]))
        claim = db.table("vouchers").update({
            "status": "active",
            "redeemed_phone": phone,
            "redeemed_at": now.isoformat(),
            "expires_at": expires.isoformat(),
        }).eq("id", v["id"]).eq("status", "unused").execute()
        if claim.data:
            v = claim.data[0]
        else:
            again = db.table("vouchers").select("*").eq("id", v["id"]).limit(1).execute().data
            if not again or again[0]["status"] != "active" or again[0].get("redeemed_phone") != phone:
                _log_attempt(db, phone, mac, ip, False)
                return _fail("invalid_voucher", INVALID_MSG)
            v = again[0]

    exp_dt = _parse(v.get("expires_at"))
    if exp_dt is None or exp_dt <= now:
        return _fail("voucher_expired", "This voucher has expired.")

    dev = db.table("devices").select("status").eq("mac_address", mac).limit(1).execute().data
    if dev and dev[0].get("status") == "blocked":
        return _fail("device_blocked", "This device is blocked. Please contact the admin.")

    expires_iso = v["expires_at"]
    max_devices = int(v["max_devices"])
    rows = db.table("voucher_devices").select("*").eq("voucher_id", v["id"]).execute().data or []
    mine = next((r for r in rows if (r.get("mac_address") or "").lower() == mac), None)
    full_msg = (f"All {max_devices} device(s) on this voucher are in use. "
                "Disconnect another device first, or ask for help.")

    if mine:
        if not _session_is_live(db, mine.get("session_id"), now):
            sid = _create_session(db, mac, phone, expires_iso)
            db.table("voucher_devices").update({"session_id": sid}).eq("id", mine["id"]).execute()
    elif len(rows) < max_devices:
        sid = _create_session(db, mac, phone, expires_iso)
        try:
            db.table("voucher_devices").insert({
                "voucher_id": v["id"], "mac_address": mac, "session_id": sid,
            }).execute()
        except Exception as e:
            _terminate_session(db, sid, "voucher_insert_failed", now)
            logger.warning(f"voucher_devices insert failed: {e}")
            again = db.table("voucher_devices").select("id").eq("voucher_id", v["id"]).eq("mac_address", mac).execute().data
            if not again:
                raise
        else:
            now_rows = db.table("voucher_devices").select("id").eq("voucher_id", v["id"]).execute().data or []
            if len(now_rows) > max_devices:
                db.table("voucher_devices").delete().eq("voucher_id", v["id"]).eq("mac_address", mac).execute()
                _terminate_session(db, sid, "voucher_devices_full", now)
                return _fail("devices_full", full_msg)
    else:
        stale_cut = now - timedelta(minutes=SLOT_STALE_MIN)
        victim = None
        for r in rows:
            d = db.table("devices").select("last_seen_at").eq("mac_address", (r.get("mac_address") or "").lower()).limit(1).execute().data
            seen = _parse(d[0].get("last_seen_at")) if d else None
            if seen is None or seen < stale_cut:
                victim = r
                break
        if not victim:
            return _fail("devices_full", full_msg)
        sid = _create_session(db, mac, phone, expires_iso)
        _terminate_session(db, victim.get("session_id"), "voucher_slot_reused", now)
        db.table("voucher_devices").update({
            "mac_address": mac, "session_id": sid,
        }).eq("id", victim["id"]).execute()

    try:
        db.table("devices").upsert({"mac_address": mac, "status": "allowed"}, on_conflict="mac_address").execute()
    except Exception as e:
        logger.warning(f"voucher device upsert failed (agent will still allow via session): {e}")

    used = len(db.table("voucher_devices").select("id").eq("voucher_id", v["id"]).execute().data or [])
    _log_attempt(db, phone, mac, ip, True)
    logger.info(f"Voucher {v['code']} redeemed by {phone} on {mac}")
    return {
        "allowed": True,
        "reason": "ok",
        "message": "Voucher accepted. Internet turns on within a few seconds.",
        "expires_at": v["expires_at"],
        "hours": round(int(v["duration_minutes"]) / 60, 2),
        "devices_used": used,
        "devices_total": max_devices,
        "phone": phone,
        "mac_address": mac,
    }


@router.post("/redeem")
async def redeem_voucher(body: RedeemBody, request: Request):
    try:
        return _redeem(body, request)
    except Exception as e:
        logger.exception(f"Voucher redeem crashed: {e}")
        return _fail("service_error", "Something went wrong. Please try again in a moment.")
