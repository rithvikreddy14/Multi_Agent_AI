from app.models.domain import User, Order
from datetime import datetime, timezone

def calculate_risk_score(user: User, order: Order, issue_type: str, has_image: bool, time_to_submit_ms: int) -> int:
    score = 0
    
    if user.total_orders <= 1 and order.amount > 20.0:
        score += 15
    if user.refunds_30d > 2:
        score += 12
    if user.refunds_90d > 3:
        score += 15
    if user.refund_ratio > 0.20:
        score += 14
    if user.flagged == 1:
        score += 25
    if not has_image and issue_type not in ["late_delivery", "missing_item"]:
        score += 18
    if time_to_submit_ms < 3000:
        score += 20
        
    if order.delivered_at:
        hours_since_delivery = (datetime.now(timezone.utc).replace(tzinfo=None) - order.delivered_at).total_seconds() / 3600
        if hours_since_delivery > 2.0:
            score += 15

    return min(score, 100)