# app/core/fraud_engine.py
"""
Nexus Fraud Detection Engine
==============================
Pure Python — zero external API calls, zero network I/O.
Target: completes in < 50 ms even on cold start.
Testable with plain mock objects (no FastAPI, no DB session needed).

Issues found in original and fixed here:
  1. Signature mismatch  — old: (user, order, issue_type, has_image, time_to_submit_ms: int)
                           new: (user, order, issue_type, has_image, image_meta: dict)
                           image_meta carries EXIF/pHash signals that were never used before.

  2. Wrong return type   — old returned int only.
                           new returns tuple[int, dict] so webhook can log which signals fired.

  3. Broken no-image rule — old excluded "missing_item" from the image requirement,
                            meaning the most common fraud vector (fake missing-item claim
                            with no photo) was never flagged. Fixed: image IS required for
                            missing_item, wrong_order, spoilage, quantity_short, packaging_damaged.

  4. time_to_submit_ms signal removed — this measured bot latency, not user behaviour,
                            and fired incorrectly whenever the server was fast.
                            Replaced with image_reuse + image_tampering from image_meta.

  5. flagged weight corrected — original used weight 25, exceeding the SRS value of 15.
                            Changed to 15 to keep score bands meaningful.

  6. None-safety added   — original would raise AttributeError if user or order is None.
                            Now returns (100, all_signals_true) as a safe maximum-risk fallback.

  7. refund_ratio comparison fixed — original compared against 0.20 (decimal).
                            DB column stores a percentage float (e.g. 22.5), so threshold
                            is now REFUND_RATIO_THRESHOLD = 20.0.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Signal weights (match SRS document exactly) ───────────────────────────
WEIGHTS: Dict[str, int] = {
    "first_order":       12,
    "repeat_30d":        12,
    "repeat_90d":        15,
    "refund_ratio":      14,
    "linked_accounts":   15,
    "high_value":        10,
    "no_image":          18,
    "image_reuse":       18,
    "image_tampering":   20,
    "delivery_mismatch": 14,
    "complaint_burst":    8,
    "new_account":        8,
    "flagged_history":   15,
    "out_of_window":     10,
}

# ── Configurable thresholds ───────────────────────────────────────────────
REFUND_30D_THRESHOLD   = 2       # > this → signal fires
REFUND_90D_THRESHOLD   = 3
REFUND_RATIO_THRESHOLD = 20.0    # percentage (domain.py stores 0–100 float)
HIGH_VALUE_THRESHOLD   = 500.0   # order amount in ₹
ACCOUNT_AGE_THRESHOLD  = 30      # days
CLAIM_WINDOW_HOURS     = 2.0     # hours after delivery
COMPLAINT_BURST_COUNT  = 5       # complaints in last 14 days
MIN_ORDERS_FOR_RATIO   = 3       # skip ratio check for brand-new accounts

# Issue types that REQUIRE an image — missing_item IS in this list (bug fix)
IMAGE_REQUIRED_TYPES = {
    "missing_item",
    "wrong_order",
    "spoilage",
    "quantity_short",
    "packaging_damaged",
}


# ── Main entry point ──────────────────────────────────────────────────────

def calculate_risk_score(
    user:       Any,
    order:      Any,
    issue_type: str             = "",
    has_image:  bool            = False,
    image_meta: Optional[Dict[str, Any]] = None,
) -> Tuple[int, Dict[str, bool]]:
    """
    Compute a 0–100 risk score.

    Parameters
    ----------
    user        SQLAlchemy User ORM row (or None → returns max risk).
                Columns used: total_orders, refunds_30d, refunds_90d,
                refund_ratio, account_age_days, flagged,
                linked_account_flag, recent_complaint_count
    order       SQLAlchemy Order ORM row (or None → returns max risk).
                Columns used: amount, delivered_at, delivery_proof, gps_anomaly
    issue_type  One of the ISSUE_MAP values from routes_webhook.py
    has_image   True if the user successfully uploaded a validated image
    image_meta  Dict returned by image_checker.validate_image.
                Keys consumed: suspicious, has_timestamp, risk_delta

    Returns
    -------
    (score, signals)
        score   : int  capped at 100
        signals : dict mapping signal name → bool (True = fired)
    """
    if image_meta is None:
        image_meta = {}

    # ── None guard ────────────────────────────────────────────────────────
    if user is None or order is None:
        logger.warning(
            "fraud_engine received None user=%s order=%s — returning max risk",
            user, order,
        )
        return 100, {k: True for k in WEIGHTS}

    score   = 0
    signals = {k: False for k in WEIGHTS}

    def _fire(name: str) -> None:
        nonlocal score
        score += WEIGHTS[name]
        signals[name] = True

    # ── 1. First-order risk ───────────────────────────────────────────────
    total_orders = int(getattr(user, "total_orders", 0) or 0)
    order_amount = float(getattr(order, "amount", 0) or 0)
    if total_orders <= 1 and order_amount > 20.0:
        _fire("first_order")

    # ── 2. Repeat refunds — 30 days ───────────────────────────────────────
    refunds_30d = int(getattr(user, "refunds_30d", 0) or 0)
    if refunds_30d > REFUND_30D_THRESHOLD:
        _fire("repeat_30d")

    # ── 3. Repeat refunds — 90 days ───────────────────────────────────────
    refunds_90d = int(getattr(user, "refunds_90d", 0) or 0)
    if refunds_90d > REFUND_90D_THRESHOLD:
        _fire("repeat_90d")

    # ── 4. Refund ratio ───────────────────────────────────────────────────
    # domain.py stores refund_ratio as a decimal (0.0–1.0) in current schema.
    # Multiply by 100 to get percentage before comparing with threshold.
    if total_orders >= MIN_ORDERS_FOR_RATIO:
        raw_ratio = float(getattr(user, "refund_ratio", 0) or 0)
        # Handle both decimal (0.22) and percentage (22.5) storage formats
        ratio_pct = raw_ratio * 100 if raw_ratio <= 1.0 else raw_ratio
        if ratio_pct >= REFUND_RATIO_THRESHOLD:
            _fire("refund_ratio")

    # ── 5. Linked accounts ────────────────────────────────────────────────
    # Set by a background job that detects shared device/IP/payment across accounts.
    # Column not yet in domain.py — defaults to False safely.
    if getattr(user, "linked_account_flag", False):
        _fire("linked_accounts")

    # ── 6. High-value claim ───────────────────────────────────────────────
    if order_amount >= HIGH_VALUE_THRESHOLD:
        _fire("high_value")

    # ── 7. No image (required for most issue types) ───────────────────────
    if issue_type in IMAGE_REQUIRED_TYPES and not has_image:
        _fire("no_image")

    # ── 8. Image reuse / 9. Image tampering ──────────────────────────────
    # image_checker sets risk_delta=18 for duplicate hash, 20 for gallery/screenshot.
    risk_delta = int(image_meta.get("risk_delta", 0))
    if risk_delta >= 18:
        # Duplicate image (pHash near-match found in claim history)
        _fire("image_reuse")
    elif image_meta.get("suspicious", False) or not image_meta.get("has_timestamp", True):
        # Gallery photo or screenshot — no EXIF timestamp
        _fire("image_tampering")

    # ── 10. Delivery mismatch ─────────────────────────────────────────────
    # Fires if delivery was marked complete but no OTP/proof recorded,
    # or if GPS anomaly was flagged by the courier system.
    # Both columns default to safe values if not yet in schema.
    delivery_proof = getattr(order, "delivery_proof", True)   # True = proof exists
    gps_anomaly    = getattr(order, "gps_anomaly",    False)
    if not delivery_proof or gps_anomaly:
        _fire("delivery_mismatch")

    # ── 11. Complaint burst ───────────────────────────────────────────────
    recent_complaints = int(getattr(user, "recent_complaint_count", 0) or 0)
    if recent_complaints >= COMPLAINT_BURST_COUNT:
        _fire("complaint_burst")

    # ── 12. New account ───────────────────────────────────────────────────
    account_age = int(getattr(user, "account_age_days", 999) or 999)
    if account_age < ACCOUNT_AGE_THRESHOLD and total_orders < 3:
        _fire("new_account")

    # ── 13. Flagged history ───────────────────────────────────────────────
    # domain.py stores flagged as Integer (0 or 1)
    if int(getattr(user, "flagged", 0) or 0) == 1:
        _fire("flagged_history")

    # ── 14. Out-of-window claim ───────────────────────────────────────────
    delivered_at = getattr(order, "delivered_at", None)
    if delivered_at:
        try:
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            # delivered_at is stored as naive UTC in domain.py
            hours_elapsed = (now - delivered_at).total_seconds() / 3600
            if hours_elapsed > CLAIM_WINDOW_HOURS:
                _fire("out_of_window")
        except Exception as exc:
            logger.warning("out_of_window check failed: %s", exc)

    # ── Cap and return ────────────────────────────────────────────────────
    score = min(score, 100)
    fired = [k for k, v in signals.items() if v]
    logger.info("FraudEngine | score=%d fired=%s issue=%s", score, fired, issue_type)
    return score, signals