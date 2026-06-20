from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.db.neon_pg import get_db
from app.models.domain import Order
from app.models.schemas import OrderTrackResponse

router = APIRouter(prefix="/order", tags=["Orders"])

@router.get("/{order_id}/track", response_model=OrderTrackResponse)
async def track_order(order_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Order).where(Order.order_id == order_id))
    order = result.scalars().first()
    
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
        
    return OrderTrackResponse(
        order_id=order.order_id,
        status=order.status,
        eta_minutes=order.eta_minutes,
        progress=order.progress,
        courier=order.courier
    )