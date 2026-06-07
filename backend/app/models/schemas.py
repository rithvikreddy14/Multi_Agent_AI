from pydantic import BaseModel, Field
from typing import Optional, Dict, Any

class OrderTrackResponse(BaseModel):
    order_id: str
    status: str
    eta_minutes: int
    progress: int
    courier: Optional[str] = None

class ImageCheckResponse(BaseModel):
    is_valid: bool
    image_hash: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

class ClaimSubmitRequest(BaseModel):
    order_id: str
    user_id: str
    issue_type: str
    description: str
    image_hash: Optional[str] = None
    image_meta: Optional[Dict[str, Any]] = None
    time_to_submit_ms: int = Field(description="Time taken to complete the funnel in MS")

class ClaimSubmitResponse(BaseModel):
    claim_id: Optional[int] = None
    decision: str
    risk_score: int
    message: str
    coupon_code: Optional[str] = None