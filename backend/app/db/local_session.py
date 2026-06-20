# app/db/local_session.py
"""
In-memory session store — drop-in replacement for Redis during local Windows dev.

Session schema (all keys):
  state           : str   — current FSM state (see STATE_* constants)
  order_id        : str   — active order being discussed
  issue_type      : str   — complaint category once selected
  image_url       : str   — Twilio MediaUrl of uploaded image
  image_hash      : str   — pHash computed from downloaded image
  image_meta      : dict  — EXIF / MIME data from image_checker
  description     : str   — free-text complaint description
  coupon_code     : str   — coupon issued (for audit)
  retry_count     : int   — consecutive unknown-input count (max 3 before soft-reset)
  created_at      : float — unix timestamp of session creation
  last_active     : float — unix timestamp of last update (for TTL check)
  user_id         : str   — resolved from DB on first contact

Upgrade path: swap the _sessions dict for a Redis client.
Every function signature stays identical — only the body changes.
"""

from typing import Dict, Any, Optional
import time

# ── Constants ──────────────────────────────────────────────────────────────
SESSION_TTL_SECONDS = 1800  # 30 minutes

# ── Valid FSM states ───────────────────────────────────────────────────────
STATE_IDLE             = "IDLE"
STATE_AWAITING_ORDER   = "AWAITING_ORDER"  # <--- ADD THIS LINE
STATE_GREETING         = "GREETING"
STATE_TRACKING         = "TRACKING"
STATE_COMPLAINT_ORDER  = "COMPLAINT_ORDER"
STATE_COMPLAINT_ISSUE  = "COMPLAINT_ISSUE"
STATE_COMPLAINT_IMAGE  = "COMPLAINT_IMAGE"
STATE_COMPLAINT_DESC   = "COMPLAINT_DESC"
STATE_FRAUD_CHECK      = "FRAUD_CHECK"
STATE_RESOLUTION_OFFER = "RESOLUTION_OFFER"
STATE_RATING           = "RATING"
STATE_ESCALATED        = "ESCALATED"
STATE_AGENT_ACTIVE     = "AGENT_ACTIVE"
STATE_MANUAL_REVIEW    = "MANUAL_REVIEW"
STATE_DENIED           = "DENIED"
STATE_ITEM_SELECT      = "ITEM_SELECT"
# ── In-memory store ────────────────────────────────────────────────────────
_sessions: Dict[str, Dict[str, Any]] = {}


# ── Internal helpers ───────────────────────────────────────────────────────

def _blank_session() -> Dict[str, Any]:
    """Return a clean session dict with all keys initialised."""
    now = time.time()
    return {
        "state":        STATE_IDLE,
        "order_id":     None,
        "issue_type":   None,
        "image_url":    None,
        "image_hash":   None,
        "image_meta":   {},
        "description":  None,
        "coupon_code":  None,
        "retry_count":  0,
        "created_at":   now,
        "last_active":  now,
        "item_name":    None,
        "item_price":   None,
        "user_id":      None,
    }


def _is_expired(session: Dict[str, Any]) -> bool:
    """Return True if the session has been idle longer than SESSION_TTL_SECONDS."""
    return (time.time() - session.get("last_active", 0)) > SESSION_TTL_SECONDS


# ── Public API ─────────────────────────────────────────────────────────────

def get_session(phone_number: str) -> Dict[str, Any]:
    """
    Return the session for this phone number.
    Creates a fresh session if none exists.
    If the existing session has expired, resets it and returns a fresh one
    (caller will see state=IDLE and handle the timeout gracefully).
    """
    if phone_number not in _sessions:
        _sessions[phone_number] = _blank_session()
        return _sessions[phone_number]

    session = _sessions[phone_number]

    if _is_expired(session):
        # Preserve user_id so account lookup is instant on re-entry
        preserved_user_id = session.get("user_id")
        _sessions[phone_number] = _blank_session()
        _sessions[phone_number]["user_id"] = preserved_user_id
        _sessions[phone_number]["state"] = "TIMEOUT"   # special one-shot state
        return _sessions[phone_number]

    return session


def set_state(phone_number: str, state: str) -> None:
    """Move the session to a new FSM state and touch last_active."""
    session = get_session(phone_number)
    session["state"] = state
    session["last_active"] = time.time()


def update_session(
    phone_number: str,
    state: str,
    *,
    order_id: Optional[str]    = None,
    issue_type: Optional[str]  = None,
    image_url: Optional[str]   = None,
    image_hash: Optional[str]  = None,
    image_meta: Optional[dict] = None,
    description: Optional[str] = None,
    coupon_code: Optional[str] = None,
    item_name: Optional[str] = None,
    item_price: Optional[float] = None,
    user_id: Optional[str]     = None,
) -> Dict[str, Any]:
    """
    Update one or many session fields atomically and advance the FSM state.
    Only fields explicitly passed (not None) are written — existing values
    for other fields are preserved.
    Returns the updated session dict.
    """
    session = get_session(phone_number)
    session["state"]       = state
    session["last_active"] = time.time()

    if order_id    is not None: session["order_id"]    = order_id
    if issue_type  is not None: session["issue_type"]  = issue_type
    if image_url   is not None: session["image_url"]   = image_url
    if image_hash  is not None: session["image_hash"]  = image_hash
    if image_meta  is not None: session["image_meta"]  = image_meta
    if description is not None: session["description"] = description
    if coupon_code is not None: session["coupon_code"] = coupon_code
    if item_name   is not None: session["item_name"]   = item_name
    if item_price  is not None: session["item_price"]  = item_price
    if user_id     is not None: session["user_id"]     = user_id

    return session


def increment_retry(phone_number: str) -> int:
    """Increment and return the retry counter. Used to soft-reset on 3 bad inputs."""
    session = get_session(phone_number)
    session["retry_count"] = session.get("retry_count", 0) + 1
    session["last_active"] = time.time()
    return session["retry_count"]


def clear_retry(phone_number: str) -> None:
    """Reset retry counter after a valid input."""
    session = get_session(phone_number)
    session["retry_count"] = 0


def reset_session(phone_number: str) -> None:
    """Wipe the session entirely. Next message starts fresh."""
    if phone_number in _sessions:
        del _sessions[phone_number]


def get_field(phone_number: str, key: str, default: Any = None) -> Any:
    """Safe single-field getter — avoids scattered session.get() calls."""
    return _sessions.get(phone_number, {}).get(key, default)