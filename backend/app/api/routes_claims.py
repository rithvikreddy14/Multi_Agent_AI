# app/api/routes_claims.py
"""
REST claim endpoints — used by the web frontend dashboard.
(WhatsApp flow uses routes_webhook.py instead.)

Changes from original:
  1. Switched AI verifier from Gemini SDK → Groq (AsyncGroq)
       Original: import google.generativeai as genai (sync SDK, blocking in async context)
       genai.GenerativeModel(...).generate_content_async() works but the genai SDK
       initialises a global state with genai.configure(api_key=...) at module load —
       this crashes if GEMINI_API_KEY is None (which it is after switching to Groq).
       Fixed: use the same AsyncGroq client already used in routes_webhook.py.

  2. Removed time_to_submit_ms from ClaimSubmitRequest and fraud engine call
       Matched to the updated schemas.py and fraud_engine.py signature.

  3. Fixed fraud engine call signature
       Old: calculate_risk_score(user, order, issue_type, has_image, time_to_submit_ms)
       New: calculate_risk_score(user, order, issue_type, has_image, image_meta)
       image_meta is now passed from request.image_meta so EXIF signals fire correctly.

  4. Fixed decision value consistency
       Old used "auto_approve" and "denied_ai" which don't match the values used in
       routes_webhook.py ("approve" and "deny"). Admin queue queries would miss records.
       Fixed: all decisions now use approve | deny | manual_review | escalate | pending.

  5. Added signals_fired to RefundClaim insert and response
       The fraud engine now returns (score, signals). Both are stored and returned.

  6. Added item_name / item_price to RefundClaim insert
       These come from the ITEM_SELECT flow in the WhatsApp bot and can also be sent
       via the REST endpoint when the frontend implements per-item selection.

  7. Added case_id generation for manual_review decisions
       The frontend needs a case ID to display to the user.

  8. AI verdict parsing changed from string check to JSON parse
       Old: "if 'suspicious' in response.text.lower()" — fragile, can false-positive
            on a phrase like "no suspicious activity found".
       New: Groq returns strict JSON via response_format=json_object. Parse the
            "action" key directly: approve | escalate | deny.

  9. Added /claim/history/{user_id} endpoint
       Required by the COMPLAINT_ORDER state in routes_webhook.py and by the
       frontend order-history view. Returns the last 10 claims for a user.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from groq import AsyncGroq
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.config import settings
from app.core.fraud_engine import calculate_risk_score
from app.db.neon_pg import get_db
from app.models.domain import Order, RefundClaim, User
from app.models.schemas import (
    AdminClaimView,
    ClaimSubmitRequest,
    ClaimSubmitResponse,
    ImageCheckResponse,
)
from app.services.image_checker import validate_and_extract_image_data

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/claim", tags=["Claims"])


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _generate_coupon(user_id: str, discount_pct: int) -> str:
    suffix = (user_id[-4:]).upper() if user_id and len(user_id) >= 4 else uuid.uuid4().hex[:4].upper()
    return f"NEXUS{discount_pct}{suffix}"


def _discount_pct(order_amount: float) -> int:
    if order_amount >= 600: return 10
    if order_amount >= 300: return 15
    return 20


def _case_id() -> str:
    return f"SUP-{uuid.uuid4().hex[:6].upper()}"


async def _groq_verify(
    issue_type:  str,
    description: str,
    image_meta:  dict,
    order_item:  str = "",
) -> dict:
    """
    Call Groq/Llama to verify a claim.
    Returns {"action": "approve"|"escalate"|"deny", "reason": str}
    Falls back to {"action": "escalate"} on any failure.
    """
    FALLBACK = {"action": "escalate", "verdict": "uncertain", "reason": "AI unavailable"}

    if not settings.GROQ_API_KEY:
        logger.error("GROQ_API_KEY missing in routes_claims")
        return FALLBACK

    system_prompt = (
        "You are a fraud analyst for a food delivery platform. "
        "Return ONLY valid JSON. Schema: "
        "{\"verdict\":\"genuine\"|\"suspicious\"|\"uncertain\","
        "\"confidence\":\"high\"|\"medium\"|\"low\","
        "\"action\":\"approve\"|\"escalate\"|\"deny\","
        "\"reason\":\"one sentence\"}."
    )
    user_prompt = (
        f"Issue type: {issue_type}\n"
        f"Item: {order_item}\n"
        f"Customer description: {description}\n"
        f"Image provided: {bool(image_meta)}\n"
        f"Image has EXIF timestamp: {image_meta.get('has_timestamp', False)}\n"
        f"Image flagged suspicious: {image_meta.get('suspicious', False)}\n"
    )

    try:
        client = AsyncGroq(api_key=settings.GROQ_API_KEY)
        resp   = await client.chat.completions.create(
            model           = "llama-3.3-70b-versatile",
            messages        = [
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt},
            ],
            response_format = {"type": "json_object"},
            temperature     = 0.0,
            max_tokens      = 200,
        )
        return json.loads(resp.choices[0].message.content)
    except Exception as exc:
        logger.error("Groq claim verify failed: %s", exc)
        return FALLBACK


# ─────────────────────────────────────────────────────────────────────────────
# ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/image-check", response_model=ImageCheckResponse)
async def check_image(file: UploadFile = File(...)):
    """
    Validate an uploaded image file (web frontend upload).
    Returns pHash and metadata for inclusion in /claim/submit.
    """
    contents = await file.read()
    result   = validate_and_extract_image_data(contents)

    if not result.get("is_valid"):
        return ImageCheckResponse(is_valid=False, error=result.get("error"))

    return ImageCheckResponse(
        is_valid   = True,
        image_hash = result["image_hash"],
        metadata   = result["metadata"],
    )


@router.post("/submit", response_model=ClaimSubmitResponse)
async def submit_claim(
    request: ClaimSubmitRequest,
    db:      AsyncSession = Depends(get_db),
):
    """
    Submit a refund/compensation claim via the web frontend.
    Runs fraud engine → AI verifier (if low risk) → saves to DB → returns decision.
    """
    # ── Resolve user and order ────────────────────────────────────────────
    user_res = await db.execute(select(User).where(User.user_id == request.user_id))
    user     = user_res.scalars().first()

    order_res = await db.execute(select(Order).where(Order.order_id == request.order_id))
    order     = order_res.scalars().first()

    if not user or not order:
        raise HTTPException(status_code=404, detail="User or Order not found.")

    # ── Duplicate claim check ─────────────────────────────────────────────
    existing_res = await db.execute(
        select(RefundClaim)
        .where(RefundClaim.order_id == request.order_id)
        .where(RefundClaim.decision.in_(["approve", "manual_review", "pending"]))
    )
    if existing_res.scalars().first():
        raise HTTPException(
            status_code=409,
            detail="A claim for this order is already being processed.",
        )

    # ── Fraud engine (no AI, < 50ms) ──────────────────────────────────────
    image_meta = request.image_meta or {}
    has_image  = request.image_hash is not None

    risk_score, signals = calculate_risk_score(
        user       = user,
        order      = order,
        issue_type = request.issue_type,
        has_image  = has_image,
        image_meta = image_meta,
    )

    decision   = "pending"
    coupon     = None
    case_id_str: str | None = None
    message    = ""

    # ── Decision bands ────────────────────────────────────────────────────
    if risk_score >= settings.FRAUD_THRESHOLD_DENY:
        decision = "deny"
        message  = "We're unable to process an automated refund for this claim."

    elif risk_score >= settings.FRAUD_THRESHOLD_AUTO_APPROVE:
        decision    = "manual_review"
        case_id_str = _case_id()
        message     = f"Your claim ({case_id_str}) has been sent for manual review. We'll respond within 24 hours."

    else:
        # ── AI verification (low-risk only) ───────────────────────────
        ai     = await _groq_verify(
            issue_type  = request.issue_type,
            description = request.description,
            image_meta  = image_meta,
            order_item  = getattr(order, "item", ""),
        )
        action = ai.get("action", "escalate")

        if action == "approve":
            pct      = _discount_pct(float(getattr(order, "amount", 0) or 0))
            coupon   = _generate_coupon(request.user_id, pct)
            decision = "approve"
            message  = f"Claim verified. Use coupon {coupon} for {pct}% off your next order."

        elif action == "deny":
            decision = "deny"
            message  = "We could not validate the issue from the provided evidence."

        else:  # uncertain / escalate
            decision    = "manual_review"
            case_id_str = _case_id()
            message     = f"Your claim ({case_id_str}) has been sent for review. We'll respond within 24 hours."

    # ── Save to DB ────────────────────────────────────────────────────────
    new_claim = RefundClaim(
        order_id      = request.order_id,
        user_id       = request.user_id,
        issue_type    = request.issue_type,
        description   = request.description,
        image_hash    = request.image_hash,
        image_meta    = image_meta or None,
        item_name     = request.item_name,
        item_price    = request.item_price,
        risk_score    = risk_score,
        decision      = decision,
        signals_fired = signals,
    )
    db.add(new_claim)
    await db.commit()
    await db.refresh(new_claim)

    return ClaimSubmitResponse(
        claim_id      = new_claim.claim_id,
        case_id       = case_id_str,
        decision      = decision,
        risk_score    = risk_score,
        message       = message,
        coupon_code   = coupon,
        signals_fired = signals,
    )


@router.get("/history/{user_id}", response_model=List[AdminClaimView])
async def claim_history(
    user_id: str,
    limit:   int = 10,
    db:      AsyncSession = Depends(get_db),
):
    """
    Return the last {limit} claims for a user.
    Used by the WhatsApp COMPLAINT_ORDER state and the frontend order-history view.
    """
    result = await db.execute(
        select(RefundClaim)
        .where(RefundClaim.user_id == user_id)
        .order_by(RefundClaim.created_at.desc())
        .limit(limit)
    )
    claims = result.scalars().all()
    return [AdminClaimView.model_validate(c) for c in claims]


@router.get("/admin/queue", response_model=List[AdminClaimView])
async def admin_review_queue(
    limit: int = 50,
    db:    AsyncSession = Depends(get_db),
):
    """
    Return all claims currently in manual_review state.
    Used by the admin panel FraudQueue.jsx component.
    """
    result = await db.execute(
        select(RefundClaim)
        .where(RefundClaim.decision == "manual_review")
        .order_by(RefundClaim.created_at.asc())   # oldest first (FIFO queue)
        .limit(limit)
    )
    claims = result.scalars().all()
    return [AdminClaimView.model_validate(c) for c in claims]