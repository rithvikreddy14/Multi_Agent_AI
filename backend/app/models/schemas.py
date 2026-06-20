# app/models/schemas.py
"""
Pydantic request/response schemas for all Nexus API endpoints.

Changes from original:
  1. ClaimSubmitRequest
       - Removed time_to_submit_ms  — this field was passed to fraud_engine but the
                                       engine now uses image_meta instead. Keeping it
                                       in the API would require the frontend to measure
                                       its own latency and send it, which is gameable.
       - Added item_name / item_price — needed when the WhatsApp ITEM_SELECT state
                                        resolves a specific affected item.
       - Added signals_fired          — optional; the fraud engine returns the dict and
                                        the web frontend can receive it for display.

  2. ClaimSubmitResponse
       - Added signals_fired          — so the admin UI can show which fraud signals fired.
       - Added case_id                — manual_review and escalated claims get a case ID.
       - Renamed 'auto_approve' → 'approve' in the decision enum to match the value
         used by routes_webhook.py (prevents mismatch between web and WhatsApp paths).

  3. OrderTrackResponse
       - Added restaurant, item, original_eta, delivery_status
         so the frontend can show more than just ETA and progress.

  4. New: ProactiveNotifyRequest
       - Schema for the POST /webhook/notify endpoint added in routes_webhook.py.

  5. New: AdminClaimView
       - Schema for the admin manual-review queue endpoint (Phase 4 admin panel).
       - Included here so it is available when the admin route is built.
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


# ─────────────────────────────────────────────────────────────────────────────
# ORDER
# ─────────────────────────────────────────────────────────────────────────────

class OrderTrackResponse(BaseModel):
    order_id:        str
    item:            Optional[str]  = None
    restaurant:      Optional[str]  = None
    status:          str
    eta_minutes:     Optional[int]  = None
    original_eta:    Optional[int]  = None   # for delay calculation
    progress:        Optional[int]  = None
    courier:         Optional[str]  = None
    delivered_at:    Optional[str]  = None   # ISO string, nullable


# ─────────────────────────────────────────────────────────────────────────────
# IMAGE CHECK  (web upload — multipart/form-data)
# ─────────────────────────────────────────────────────────────────────────────

class ImageCheckResponse(BaseModel):
    is_valid:    bool
    image_hash:  Optional[str]            = None
    metadata:    Optional[Dict[str, Any]] = None
    error:       Optional[str]            = None


# ─────────────────────────────────────────────────────────────────────────────
# CLAIM SUBMIT  (web REST endpoint — used by frontend dashboard)
# ─────────────────────────────────────────────────────────────────────────────

class ClaimSubmitRequest(BaseModel):
    order_id:    str   = Field(..., description="Order ID, e.g. ORD-4521")
    user_id:     str   = Field(..., description="User ID, e.g. USR-100")
    issue_type:  str   = Field(
        ...,
        description=(
            "One of: missing_item | wrong_order | spoilage | late_delivery | "
            "quantity_short | packaging_damaged | other"
        ),
    )
    description: str   = Field(..., min_length=3, description="Customer's free-text description")
    image_hash:  Optional[str]            = None
    image_meta:  Optional[Dict[str, Any]] = None
    item_name:   Optional[str]            = None   # specific item from ITEM_SELECT flow
    item_price:  Optional[float]          = None   # price of the specific affected item

    @field_validator("issue_type")
    @classmethod
    def validate_issue_type(cls, v: str) -> str:
        valid = {
            "missing_item", "wrong_order", "spoilage",
            "late_delivery", "quantity_short", "packaging_damaged", "other",
        }
        if v not in valid:
            raise ValueError(f"issue_type must be one of: {', '.join(sorted(valid))}")
        return v


class ClaimSubmitResponse(BaseModel):
    claim_id:      Optional[int]             = None
    case_id:       Optional[str]             = None   # SUP-XXXXXX for manual_review/escalate
    decision:      str
    # decision values: approve | deny | manual_review | escalate | pending
    risk_score:    int
    message:       str
    coupon_code:   Optional[str]             = None
    signals_fired: Optional[Dict[str, bool]] = None   # which fraud signals fired


# ─────────────────────────────────────────────────────────────────────────────
# PROACTIVE NOTIFICATION  (POST /webhook/notify — called by background job)
# ─────────────────────────────────────────────────────────────────────────────

class ProactiveNotifyRequest(BaseModel):
    phone_number: str   = Field(..., description="E.164 format, e.g. +919876543210")
    event:        str   = Field(
        ...,
        description="One of: picked_up | delivered | delayed",
    )
    item:         str   = ""
    courier:      str   = ""
    eta:          int   = 0
    delay_min:    int   = 0
    delivered_at: str   = ""

    @field_validator("event")
    @classmethod
    def validate_event(cls, v: str) -> str:
        if v not in {"picked_up", "delivered", "delayed"}:
            raise ValueError("event must be one of: picked_up, delivered, delayed")
        return v


# ─────────────────────────────────────────────────────────────────────────────
# ADMIN — CLAIM QUEUE VIEW  (Phase 4 admin panel)
# ─────────────────────────────────────────────────────────────────────────────

class AdminClaimView(BaseModel):
    """
    Read schema for the manual-review queue in the admin panel.
    Maps directly to RefundClaim ORM columns.
    """
    claim_id:      int
    order_id:      str
    user_id:       str
    issue_type:    str
    description:   Optional[str]             = None
    image_hash:    Optional[str]             = None
    item_name:     Optional[str]             = None
    item_price:    Optional[float]           = None
    risk_score:    int
    decision:      str
    signals_fired: Optional[Dict[str, bool]] = None
    csat_rating:   Optional[int]             = None
    created_at:    Optional[str]             = None   # ISO datetime string

    model_config = {"from_attributes": True}   # enables ORM mode (pydantic v2)