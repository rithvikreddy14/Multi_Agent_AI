from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.db.neon_pg import get_db
from app.models.domain import User, Order, RefundClaim
from app.models.schemas import ClaimSubmitRequest, ClaimSubmitResponse, ImageCheckResponse
from app.services.image_checker import validate_and_extract_image_data
from app.core.fraud_engine import calculate_risk_score
from app.core.config import settings
import google.generativeai as genai
import uuid

router = APIRouter(prefix="/claim", tags=["Claims"])

genai.configure(api_key=settings.GEMINI_API_KEY)

@router.post("/image-check", response_model=ImageCheckResponse)
async def check_image(file: UploadFile = File(...)):
    contents = await file.read()
    result = validate_and_extract_image_data(contents)
    if not result.get("is_valid"):
        return ImageCheckResponse(is_valid=False, error=result.get("error"))
    return ImageCheckResponse(
        is_valid=True, 
        image_hash=result["image_hash"], 
        metadata=result["metadata"]
    )

@router.post("/submit", response_model=ClaimSubmitResponse)
async def submit_claim(request: ClaimSubmitRequest, db: AsyncSession = Depends(get_db)):
    user_res = await db.execute(select(User).where(User.user_id == request.user_id))
    user = user_res.scalars().first()
    
    order_res = await db.execute(select(Order).where(Order.order_id == request.order_id))
    order = order_res.scalars().first()
    
    if not user or not order:
        raise HTTPException(status_code=404, detail="User or Order not found")

    has_image = request.image_hash is not None
    risk_score = calculate_risk_score(user, order, request.issue_type, has_image, request.time_to_submit_ms)
    
    decision = "pending"
    coupon = None
    message = ""

    if risk_score >= settings.FRAUD_THRESHOLD_DENY:
        decision = "deny"
        message = "Claim denied due to policy violations."
    elif risk_score >= settings.FRAUD_THRESHOLD_AUTO_APPROVE:
        decision = "manual_review"
        message = "Your claim requires manual verification by our team."
    else:
        try:
            model = genai.GenerativeModel('gemini-1.5-flash', generation_config={"response_mime_type": "application/json"})
            prompt = f"""
            Analyze this complaint: Issue Type: {request.issue_type}. Description: {request.description}.
            Return JSON with keys: "verdict" (either "genuine" or "suspicious"), and "reason".
            """
            response = await model.generate_content_async(prompt)
            if "suspicious" in response.text.lower():
                decision = "denied_ai"
                message = "We could not validate the issue from the provided evidence."
            else:
                decision = "auto_approve"
                coupon = f"COMP-{uuid.uuid4().hex[:8].upper()}"
                message = "We apologize for the issue. Here is a compensation coupon."
        except Exception as e:
            decision = "manual_review"
            message = "Experiencing high volume. Claim sent to manual review."

    new_claim = RefundClaim(
        order_id=request.order_id,
        user_id=request.user_id,
        issue_type=request.issue_type,
        description=request.description,
        image_hash=request.image_hash,
        image_meta=request.image_meta,
        risk_score=risk_score,
        decision=decision
    )
    db.add(new_claim)
    await db.commit()
    await db.refresh(new_claim)

    return ClaimSubmitResponse(
        claim_id=new_claim.claim_id,
        decision=decision,
        risk_score=risk_score,
        message=message,
        coupon_code=coupon
    )