from sqlalchemy import Column, String, Integer, Float, DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import declarative_base
from datetime import datetime, timezone

Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    user_id = Column(String, primary_key=True, index=True)
    account_age_days = Column(Integer)
    total_orders = Column(Integer)
    refunds_30d = Column(Integer)
    refunds_90d = Column(Integer)
    refund_ratio = Column(Float)
    flagged = Column(Integer, default=0)

class Order(Base):
    __tablename__ = "orders"
    order_id = Column(String, primary_key=True, index=True)
    user_id = Column(String, ForeignKey("users.user_id"))
    item = Column(String)
    restaurant = Column(String)
    status = Column(String)
    courier = Column(String)
    eta_minutes = Column(Integer)
    progress = Column(Integer)
    placed_at = Column(DateTime)
    delivered_at = Column(DateTime, nullable=True)
    amount = Column(Float)

class RefundClaim(Base):
    __tablename__ = "refund_claims"
    claim_id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(String, ForeignKey("orders.order_id"))
    user_id = Column(String, ForeignKey("users.user_id"))
    issue_type = Column(String)
    description = Column(Text)
    image_hash = Column(String, nullable=True)
    image_meta = Column(JSONB, nullable=True)
    risk_score = Column(Integer)
    decision = Column(String)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))