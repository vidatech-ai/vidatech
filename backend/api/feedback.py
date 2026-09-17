# =============================================================================
# VIDATECH WIFI — Feedback API
# backend/api/feedback.py
# =============================================================================

import logging
from typing import Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from auth.dependencies import require_admin
from db import get_db
from utils import utcnow

logger = logging.getLogger("vidatech.feedback")
router = APIRouter()


class FeedbackSubmit(BaseModel):
    phone: Optional[str] = None
    connected_at: Optional[str] = None
    message: str


class FeedbackReply(BaseModel):
    admin_reply: str


@router.post("/")
async def submit_feedback(body: FeedbackSubmit):
    """Public — anyone can submit feedback."""
    db = get_db()
    if not body.message.strip():
        return {"ok": False, "error": "Message is required."}
    db.table("feedback").insert({
        "phone": body.phone or None,
        "connected_at": body.connected_at or None,
        "message": body.message.strip(),
        "created_at": utcnow().isoformat(),
    }).execute()
    return {"ok": True}


@router.get("/")
async def list_feedback(admin=Depends(require_admin)):
    """Admin only — list all feedback newest first."""
    db = get_db()
    result = db.table("feedback").select("*").order("created_at", desc=True).execute()
    return result.data


@router.patch("/{feedback_id}/reply")
async def reply_feedback(feedback_id: str, body: FeedbackReply, admin=Depends(require_admin)):
    """Admin only — save a reply to a feedback entry."""
    db = get_db()
    db.table("feedback").update({
        "admin_reply": body.admin_reply.strip(),
    }).eq("id", feedback_id).execute()
    return {"ok": True}
