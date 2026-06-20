# app/api/routes_webhook.py
"""
Nexus WhatsApp Support Bot — Finalized Pipeline
=================================================
Every inbound WhatsApp message flows through these layers in order:

  1.  Twilio signature validation          (security)
  2.  Phone number + media-type parse      (input normalisation)
  3.  Session fetch + TTL / timeout check  (state management)
  4.  User account resolution              (DB, no AI)
  5.  AGENT_ACTIVE silence gate            (human handoff)
  6.  Global greeting interrupt            (reset at any point)
  7.  Retry counter + soft-reset           (loop prevention)
  8.  FSM dispatch                         (state-specific handlers)
      ├── IDLE            → order ID entry
      ├── AWAITING_ORDER  → order lookup + greeting
      ├── GREETING        → track / complaint / escalate
      ├── TRACKING        → live status (no AI)
      ├── COMPLAINT_ISSUE → 7-option issue type menu
      ├── ITEM_SELECT     → per-item selection (Zomato feature)
      ├── COMPLAINT_IMAGE → image download + full validation pipeline
      ├── COMPLAINT_DESC  → free-text + fraud engine + AI verifier
      ├── RESOLUTION_OFFER→ accept coupon or escalate
      ├── RATING          → CSAT collection (saves to DB)
      ├── DENIED          → options after denial
      └── MANUAL_REVIEW   → waiting state with agent option
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from groq import AsyncGroq
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from twilio.request_validator import RequestValidator
from twilio.twiml.messaging_response import MessagingResponse

from app.core.config import settings
from app.core.fraud_engine import calculate_risk_score
from app.db.local_session import (
    STATE_AGENT_ACTIVE, STATE_AWAITING_ORDER, STATE_COMPLAINT_DESC,
    STATE_COMPLAINT_IMAGE, STATE_COMPLAINT_ISSUE, STATE_COMPLAINT_ORDER,
    STATE_DENIED, STATE_ESCALATED, STATE_GREETING, STATE_IDLE,
    STATE_ITEM_SELECT, STATE_MANUAL_REVIEW, STATE_RATING,
    STATE_RESOLUTION_OFFER, STATE_TRACKING,
    clear_retry, get_field, get_session, increment_retry,
    reset_session, set_state, update_session,
)
from app.db.neon_pg import get_db
from app.models.domain import Order, OrderItem, RefundClaim, User
from app.services.image_checker import validate_image
from app.core.bot_templates import (
    ERR_ORDER_NOT_FOUND, ERR_PLEASE_REPLY_NUMBER, ERR_TOO_MANY_RETRIES,
    ERR_UNKNOWN, ERR_VIDEO, ERR_VOICE_NOTE,
    notif_order_delivered, notif_order_delayed, notif_order_picked_up,
    tmpl_already_refunded, tmpl_complaint_issue_menu, tmpl_complaint_select_item,
    tmpl_complaint_select_order, tmpl_greeting_active, tmpl_greeting_no_order,
    tmpl_greeting_timeout_return, tmpl_image_invalid_duplicate,
    tmpl_image_invalid_format, tmpl_image_invalid_no_exif, tmpl_image_invalid_size,
    tmpl_image_received, tmpl_image_request, tmpl_late_arrived_coupon,
    tmpl_late_delivery_request, tmpl_order_never_arrived, tmpl_out_of_window,
    tmpl_processing, tmpl_rating_thanks, tmpl_resolution_coupon,
    tmpl_resolution_denied, tmpl_resolution_escalate, tmpl_resolution_manual_review,
    tmpl_resolution_satisfied, tmpl_still_waiting_track, tmpl_tracking_delayed,
    tmpl_tracking_delivered, tmpl_tracking_on_the_way, tmpl_tracking_preparing,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhook", tags=["Omnichannel"])

MAX_RETRIES           = 4
FRAUD_DENY_THRESHOLD  = 60
FRAUD_REVIEW_THRESH   = 40
CLAIM_WINDOW_HOURS    = 2.0
DEFAULT_AGENT_NAME    = "Priya R."
DEFAULT_AGENT_ETA     = 5

ISSUE_MAP: dict[str, str] = {
    "1": "missing_item", "2": "wrong_order", "3": "spoilage",
    "4": "late_delivery", "5": "quantity_short",
    "6": "packaging_damaged", "7": "other",
}
ITEM_SELECT_ISSUES = {"missing_item", "wrong_order"}
NO_IMAGE_REQUIRED  = {"late_delivery", "other"}

# ── Helpers ───────────────────────────────────────────────────────────────

def _twiml(text: str) -> Response:
    r = MessagingResponse()
    r.message(text)
    print(f"\n[BOT REPLY] → {text[:120]}\n")
    return Response(content=str(r), media_type="application/xml; charset=utf-8")

def _empty_twiml() -> Response:
    return Response(content=str(MessagingResponse()), media_type="application/xml")

def _case_id() -> str:
    return f"SUP-{uuid.uuid4().hex[:6].upper()}"

def _coupon_code(user_id: str, discount_pct: int) -> str:
    suffix = (user_id[-4:]).upper() if user_id and len(user_id) >= 4 else uuid.uuid4().hex[:4].upper()
    return f"NEXUS{discount_pct}{suffix}"

def _discount_pct(order_amount: float) -> int:
    if order_amount >= 600: return 10
    if order_amount >= 300: return 15
    return 20

# ── Intent detection ──────────────────────────────────────────────────────

def detect_intent(text: str) -> str:
    t = text.lower().strip()
    if not t:                                                                   return "empty"
    if t.isdigit():                                                             return "number"
    if re.search(r'\b(hi|hello|hey|menu|start|restart)\b', t):                 return "greeting"
    if re.search(r'\b(track|where|eta|status|location)\b', t):                 return "tracking"
    if re.search(r'\b(missing|wrong|bad|spoil|rotten|complaint|issue|problem|refund)\b', t): return "complaint"
    if re.search(r'\b(agent|human|support|speak|person|team)\b', t):           return "escalate"
    if re.search(r'\b(yes|yeah|yep|ok|okay|sure)\b', t):                       return "affirm"
    if re.search(r'\b(no|nope|nah)\b', t):                                     return "deny"
    return "unknown"

# ── DB helpers ────────────────────────────────────────────────────────────

async def _get_order(order_id: str, db: AsyncSession) -> Optional[Order]:
    r = await db.execute(select(Order).where(Order.order_id == order_id))
    return r.scalars().first()

async def _get_user(user_id: str, db: AsyncSession) -> Optional[User]:
    r = await db.execute(select(User).where(User.user_id == user_id))
    return r.scalars().first()

async def _get_items(order_id: str, db: AsyncSession):
    r = await db.execute(select(OrderItem).where(OrderItem.order_id == order_id))
    return r.scalars().all()

async def _existing_claim(order_id: str, db: AsyncSession) -> Optional[RefundClaim]:
    r = await db.execute(
        select(RefundClaim)
        .where(RefundClaim.order_id == order_id)
        .where(RefundClaim.decision.in_(["approve", "manual_review", "pending"]))
    )
    return r.scalars().first()

def _hours_since_delivery(order: Order) -> Optional[float]:
    import datetime
    if not getattr(order, "delivered_at", None):
        return None
    now = datetime.datetime.utcnow()
    delivered = order.delivered_at
    if getattr(delivered, "tzinfo", None):
        now = now.replace(tzinfo=datetime.timezone.utc)
    return (now - delivered).total_seconds() / 3600

# ── AI verifier ───────────────────────────────────────────────────────────

async def _ai_verify(order: Order, issue_type: str, description: str, image_meta: dict) -> dict:
    FALLBACK = {"verdict": "uncertain", "action": "escalate", "confidence": "low", "reason": "AI unavailable"}
    if not settings.GROQ_API_KEY:
        logger.error("GROQ_API_KEY missing")
        return FALLBACK
    system_prompt = (
        "You are a fraud analyst for a food delivery platform. Return ONLY valid JSON. Schema: "
        "{\"verdict\":\"genuine\"|\"suspicious\"|\"uncertain\","
        "\"confidence\":\"high\"|\"medium\"|\"low\","
        "\"action\":\"approve\"|\"escalate\"|\"deny\","
        "\"reason\":\"one sentence\"}."
    )
    user_prompt = (
        f"Order item: {getattr(order,'item','Unknown')}\n"
        f"Restaurant: {getattr(order,'restaurant','Unknown')}\n"
        f"Order amount: {getattr(order,'amount',0)}\n"
        f"Issue type: {issue_type}\n"
        f"Customer description: {description}\n"
        f"Image provided: {bool(image_meta)}\n"
        f"Image has EXIF timestamp: {image_meta.get('has_timestamp', False)}\n"
        f"Image has GPS: {image_meta.get('has_gps', False)}\n"
        f"Image flagged suspicious: {image_meta.get('suspicious', False)}\n"
    )
    try:
        client = AsyncGroq(api_key=settings.GROQ_API_KEY)
        resp   = await client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role":"system","content":system_prompt},{"role":"user","content":user_prompt}],
            response_format={"type":"json_object"},
            temperature=0.0, max_tokens=200,
        )
        return json.loads(resp.choices[0].message.content)
    except Exception as exc:
        logger.error("Groq verify failed: %s", exc)
        return FALLBACK

async def _validate_twilio_signature(request: Request) -> None:
    if not settings.TWILIO_AUTH_TOKEN: return
    validator = RequestValidator(settings.TWILIO_AUTH_TOKEN)
    if not validator.validate(str(request.url), dict(await request.form()), request.headers.get("X-Twilio-Signature","")):
        raise HTTPException(status_code=403, detail="Invalid Twilio signature")

def _save_claim(db, order_id, user_id, issue_type, description, session, risk_score, decision) -> RefundClaim:
    claim = RefundClaim(
        order_id=order_id, user_id=user_id, issue_type=issue_type,
        description=description, image_hash=session.get("image_hash"),
        image_meta=session.get("image_meta", {}), item_name=session.get("item_name"),
        risk_score=risk_score, decision=decision,
    )
    db.add(claim)
    return claim

# ── MAIN WEBHOOK ──────────────────────────────────────────────────────────

@router.post("/whatsapp")
async def whatsapp_webhook(
    request:           Request,
    From:              str           = Form(...),
    Body:              str           = Form(""),
    NumMedia:          int           = Form(0),
    MediaUrl0:         Optional[str] = Form(None),
    MediaContentType0: Optional[str] = Form(None),
    db:                AsyncSession  = Depends(get_db),
):
    await _validate_twilio_signature(request)

    phone   = From.replace("whatsapp:", "").strip()
    raw_inp = Body.strip()
    intent  = detect_intent(raw_inp)
    inp     = raw_inp.lower()

    session = get_session(phone)
    state   = session.get("state", STATE_IDLE)

    logger.info("WA | phone=%s state=%s intent=%s media=%d", phone, state, intent, NumMedia)

    # Media-type guard
    if NumMedia > 0 and MediaContentType0:
        ct = MediaContentType0.lower()
        if "audio" in ct or "ogg" in ct: return _twiml(ERR_VOICE_NOTE)
        if "video" in ct:                return _twiml(ERR_VIDEO)

    # Timeout recovery
    if state == "TIMEOUT":
        uid = session.get("user_id")
        if uid:
            r = await db.execute(
                select(Order).where(Order.user_id==uid)
                .where(Order.status.notin_(["delivered","cancelled"]))
                .order_by(Order.placed_at.desc())
            )
            order = r.scalars().first()
            if order:
                update_session(phone, STATE_GREETING, order_id=order.order_id, user_id=uid)
                return _twiml(tmpl_greeting_timeout_return(order.order_id, order.item, order.restaurant))
        reset_session(phone)
        return _twiml("Session expired. Say *Hi* to start over. 👋")

    # Agent active gate
    if state == STATE_AGENT_ACTIVE:
        if intent == "greeting" or inp in ("menu","restart"):
            reset_session(phone); state = STATE_IDLE
        else:
            return _empty_twiml()

    # Global greeting reset
    if intent == "greeting" and state not in (STATE_IDLE, STATE_GREETING, STATE_AGENT_ACTIVE):
        reset_session(phone); state = STATE_IDLE

    # Retry counter
    if intent == "unknown":
        if increment_retry(phone) >= MAX_RETRIES:
            reset_session(phone)
            return _twiml(ERR_TOO_MANY_RETRIES)
    else:
        clear_retry(phone)

    # ── FSM ───────────────────────────────────────────────────────────────

    if state == STATE_IDLE:
        update_session(phone, STATE_AWAITING_ORDER)
        return _twiml("Hi! 👋 Welcome to Nexus Support.\n\nPlease enter your Order ID to continue (e.g., ORD-1001):")

    elif state == STATE_AWAITING_ORDER:
        order = await _get_order(raw_inp.upper(), db)
        if not order:
            return _twiml("No order found with that ID. Please check and try again (e.g. ORD-1001).")
        update_session(phone, STATE_GREETING, order_id=order.order_id, user_id=order.user_id)
        return _twiml(tmpl_greeting_active(order.order_id, order.item, order.restaurant))

    elif state == STATE_GREETING:
        order_id = session.get("order_id")
        order    = await _get_order(order_id, db) if order_id else None
        if inp == "1" or intent == "tracking":
            if not order: return _twiml(ERR_ORDER_NOT_FOUND)
            update_session(phone, STATE_TRACKING)
            status = getattr(order, "status", "on_the_way")
            if status == "preparing":
                return _twiml(tmpl_tracking_preparing(order.restaurant, order.eta_minutes or 10))
            if status == "delivered":
                dt = order.delivered_at
                return _twiml(tmpl_tracking_delivered(dt.strftime("%I:%M %p") if dt else "recently"))
            orig = getattr(order, "original_eta", None)
            if orig and order.eta_minutes and order.eta_minutes > orig:
                return _twiml(tmpl_tracking_delayed(order.eta_minutes, order.eta_minutes - orig))
            return _twiml(tmpl_tracking_on_the_way(order.courier or "your courier", order.eta_minutes or 20, order.progress or 50))
        elif inp == "2" or intent == "complaint":
            if not order: return _twiml(ERR_ORDER_NOT_FOUND)
            update_session(phone, STATE_COMPLAINT_ISSUE)
            return _twiml(tmpl_complaint_issue_menu(order.order_id, order.item))
        elif inp == "3" or intent == "escalate":
            update_session(phone, STATE_AGENT_ACTIVE)
            return _twiml(tmpl_resolution_escalate(_case_id(), DEFAULT_AGENT_NAME, DEFAULT_AGENT_ETA))
        return _twiml(ERR_UNKNOWN)

    elif state == STATE_TRACKING:
        order_id = session.get("order_id")
        order    = await _get_order(order_id, db) if order_id else None
        if inp == "1" or intent == "complaint":
            if not order: return _twiml(ERR_ORDER_NOT_FOUND)
            update_session(phone, STATE_COMPLAINT_ISSUE, order_id=order_id)
            return _twiml(tmpl_complaint_issue_menu(order_id, order.item))
        elif inp == "2" or intent == "escalate":
            update_session(phone, STATE_AGENT_ACTIVE)
            return _twiml(tmpl_resolution_escalate(_case_id(), DEFAULT_AGENT_NAME, DEFAULT_AGENT_ETA))
        elif inp == "3" or intent == "affirm":
            reset_session(phone)
            return _twiml("Thanks for using Nexus! Have a great day. 👋")
        if intent == "tracking" and order:
            return _twiml(tmpl_tracking_on_the_way(order.courier or "your courier", order.eta_minutes or 20, order.progress or 50))
        return _twiml(ERR_UNKNOWN)

    elif state == STATE_COMPLAINT_ISSUE:
        order_id = session.get("order_id")
        order    = await _get_order(order_id, db) if order_id else None
        selected_issue: Optional[str] = ISSUE_MAP.get(inp)
        if not selected_issue:
            return _twiml(ERR_PLEASE_REPLY_NUMBER)
        # Already refunded check
        existing = await _existing_claim(order_id, db)
        if existing:
            dt_str  = existing.created_at.strftime("%d %b") if getattr(existing,"created_at",None) else "recently"
            amt_str = f"₹{existing.amount}" if getattr(existing,"amount",None) else ""
            return _twiml(tmpl_already_refunded(order_id, dt_str, amt_str))
        # Claim window check
        if order and getattr(order,"status","") == "delivered":
            hours = _hours_since_delivery(order)
            if hours is not None and hours > CLAIM_WINDOW_HOURS:
                return _twiml(tmpl_out_of_window(hours))
        # Late delivery
        if selected_issue == "late_delivery":
            update_session(phone, STATE_COMPLAINT_DESC, issue_type=selected_issue)
            return _twiml(tmpl_late_delivery_request())
        # Per-item selection
        if selected_issue in ITEM_SELECT_ISSUES:
            items = await _get_items(order_id, db)
            if items:
                items_text = "\n".join(f"{i+1}️⃣ {item.name} (₹{item.price})" for i, item in enumerate(items))
                update_session(phone, STATE_ITEM_SELECT, issue_type=selected_issue)
                return _twiml(tmpl_complaint_select_item(items_text))
        update_session(phone, STATE_COMPLAINT_IMAGE, issue_type=selected_issue)
        return _twiml(tmpl_image_request(selected_issue))

    elif state == STATE_ITEM_SELECT:
        order_id = session.get("order_id")
        items    = await _get_items(order_id, db)
        if inp.isdigit() and 1 <= int(inp) <= len(items):
            chosen = items[int(inp)-1]
            update_session(phone, STATE_COMPLAINT_IMAGE, item_name=chosen.name, item_price=chosen.price)
            return _twiml(tmpl_image_request(session.get("issue_type","missing_item")))
        return _twiml(ERR_PLEASE_REPLY_NUMBER)

    elif state == STATE_COMPLAINT_IMAGE:
        if NumMedia == 0 or not MediaUrl0:
            return _twiml(tmpl_image_request(session.get("issue_type","missing_item")))
        user_id = session.get("user_id")
        check   = await validate_image(
            media_url=MediaUrl0, phone_number=phone, db=db, user_id=user_id,
            twilio_account_sid=settings.TWILIO_ACCOUNT_SID,
            twilio_auth_token=settings.TWILIO_AUTH_TOKEN,
        )
        if not check.valid:
            if check.rejection_reason == "duplicate":  return _twiml(tmpl_image_invalid_duplicate())
            if check.rejection_reason == "too_large":  return _twiml(tmpl_image_invalid_size())
            if check.rejection_reason == "bad_format": return _twiml(tmpl_image_invalid_format())
            return _twiml(tmpl_image_invalid_no_exif())
        update_session(phone, STATE_COMPLAINT_DESC,
            image_url=MediaUrl0, image_hash=check.image_hash,
            image_meta={**check.image_meta, "risk_delta": check.risk_delta})
        return _twiml(tmpl_image_received())

    elif state == STATE_COMPLAINT_DESC:
        issue_type = session.get("issue_type","")
        order_id   = session.get("order_id")
        user_id    = session.get("user_id","USR-100")
        # Late delivery sub-flow
        if issue_type == "late_delivery":
            if inp == "1" or intent == "affirm":
                coupon = _coupon_code(user_id, 15)
                update_session(phone, STATE_RESOLUTION_OFFER, coupon_code=coupon)
                return _twiml(tmpl_late_arrived_coupon(coupon, 15))
            elif inp == "2":
                order = await _get_order(order_id, db)
                if order:
                    update_session(phone, STATE_TRACKING)
                    return _twiml(tmpl_still_waiting_track(order.courier or "your courier", order.eta_minutes or 20))
                return _twiml(ERR_ORDER_NOT_FOUND)
            elif inp == "3":
                update_session(phone, STATE_ESCALATED)
                return _twiml(tmpl_order_never_arrived() + f"\n\n📋 Priority Case ID: {_case_id()}")
            return _twiml(ERR_PLEASE_REPLY_NUMBER)
        # Standard description
        if len(raw_inp) < 3:
            return _twiml("Please describe the issue in a few words so I can help. 🙏")
        description = raw_inp
        image_meta  = session.get("image_meta", {})
        update_session(phone, "FRAUD_CHECK", description=description)
        # Fraud engine
        user_obj  = await _get_user(user_id, db)
        order_obj = await _get_order(order_id, db)
        risk_score, signals = calculate_risk_score(
            user=user_obj, order=order_obj, issue_type=issue_type,
            has_image=bool(session.get("image_hash")), image_meta=image_meta,
        )
        logger.info("Fraud | score=%d phone=%s", risk_score, phone)
        if risk_score >= FRAUD_DENY_THRESHOLD:
            _save_claim(db, order_id, user_id, issue_type, description, session, risk_score, "deny")
            await db.commit()
            update_session(phone, STATE_DENIED)
            return _twiml(tmpl_resolution_denied())
        if risk_score >= FRAUD_REVIEW_THRESH:
            case = _case_id()
            _save_claim(db, order_id, user_id, issue_type, description, session, risk_score, "manual_review")
            await db.commit()
            update_session(phone, STATE_MANUAL_REVIEW)
            return _twiml(tmpl_resolution_manual_review(case))
        # AI verification
        ai     = await _ai_verify(order_obj, issue_type, description, image_meta)
        action = ai.get("action","escalate")
        logger.info("AI verdict | action=%s phone=%s", action, phone)
        _save_claim(db, order_id, user_id, issue_type, description, session, risk_score, action)
        await db.commit()
        if action == "approve":
            pct    = _discount_pct(float(getattr(order_obj,"amount",0) or 0))
            coupon = _coupon_code(user_id, pct)
            update_session(phone, STATE_RESOLUTION_OFFER, coupon_code=coupon)
            return _twiml(tmpl_resolution_coupon(coupon, pct, valid_days=7))
        if action == "deny":
            update_session(phone, STATE_DENIED)
            return _twiml(tmpl_resolution_denied())
        update_session(phone, STATE_MANUAL_REVIEW)
        return _twiml(tmpl_resolution_manual_review(_case_id()))

    elif state == STATE_RESOLUTION_OFFER:
        if inp == "1" or intent == "affirm":
            set_state(phone, STATE_RATING)
            return _twiml(tmpl_resolution_satisfied())
        elif inp == "2" or intent == "deny":
            update_session(phone, STATE_ESCALATED)
            return _twiml(tmpl_resolution_escalate(_case_id(), DEFAULT_AGENT_NAME, DEFAULT_AGENT_ETA))
        return _twiml(ERR_PLEASE_REPLY_NUMBER)

    elif state == STATE_RATING:
        rating = {"1":1,"2":2,"3":3}.get(inp)
        if rating is None and intent == "affirm": rating = 1
        if rating:
            order_id = session.get("order_id")
            if order_id:
                r = await db.execute(
                    select(RefundClaim).where(RefundClaim.order_id==order_id)
                    .order_by(RefundClaim.created_at.desc())
                )
                claim = r.scalars().first()
                if claim and hasattr(claim,"csat_rating"):
                    claim.csat_rating = rating
                    await db.commit()
            reset_session(phone)
            return _twiml(tmpl_rating_thanks(rating))
        return _twiml("Please reply with 1, 2, or 3 to rate your experience. ⭐")

    elif state == STATE_DENIED:
        if inp == "1" or intent == "escalate":
            update_session(phone, STATE_AGENT_ACTIVE)
            return _twiml(tmpl_resolution_escalate(_case_id(), DEFAULT_AGENT_NAME, DEFAULT_AGENT_ETA))
        elif inp == "2":
            update_session(phone, STATE_COMPLAINT_IMAGE)
            return _twiml(tmpl_image_request(session.get("issue_type","other")))
        elif inp == "3":
            reset_session(phone)
            return _twiml("Understood. You can also reach us through the app. 🙏 Have a great day!")
        return _twiml(ERR_PLEASE_REPLY_NUMBER)

    elif state == STATE_MANUAL_REVIEW:
        if intent == "escalate" or inp == "1":
            update_session(phone, STATE_AGENT_ACTIVE)
            return _twiml(tmpl_resolution_escalate(_case_id(), DEFAULT_AGENT_NAME, DEFAULT_AGENT_ETA))
        return _twiml("Your case is with our review team. 🙏\n\nYou'll receive a reply within 24 hours.\n\n1️⃣ I'd prefer to speak to someone now")

    elif state == STATE_ESCALATED:
        update_session(phone, STATE_AGENT_ACTIVE)
        return _empty_twiml()

    else:
        logger.warning("Unknown state=%s phone=%s — resetting", state, phone)
        reset_session(phone)
        return _twiml("Session reset. Say *Hi* to start over. 👋")


# ── Proactive notification endpoint ───────────────────────────────────────

@router.post("/notify")
async def send_proactive_notification(
    phone_number: str, event: str,
    item: str="", courier: str="", eta: int=0,
    delay_min: int=0, delivered_at: str="",
):
    from twilio.rest import Client
    if not settings.TWILIO_ACCOUNT_SID or not settings.TWILIO_WHATSAPP_FROM:
        return {"status": "error", "reason": "not_configured"}
    if event == "picked_up":   body = notif_order_picked_up(item, courier, eta)
    elif event == "delivered": body = notif_order_delivered(item, delivered_at or "just now")
    elif event == "delayed":   body = notif_order_delayed(item, delay_min, eta)
    else:                      return {"status":"error","reason":f"unknown event {event}"}
    try:
        Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN).messages.create(
            from_=f"whatsapp:{settings.TWILIO_WHATSAPP_FROM}",
            to=f"whatsapp:{phone_number}", body=body,
        )
        return {"status":"sent"}
    except Exception as exc:
        logger.error("Notification failed: %s", exc)
        return {"status":"error","reason":str(exc)}