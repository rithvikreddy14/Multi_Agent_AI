# app/models/domain.py
"""
SQLAlchemy ORM models for Nexus platform.

Changes from original:
  1. User table
       + phone_number          — required for WhatsApp account lookup by phone.
                                 Without this, the webhook cannot resolve who is messaging.
       + linked_account_flag   — set by background job when device/IP/payment shared
                                 across multiple accounts. Used by fraud_engine signal 5.
       + recent_complaint_count— count of complaints in last 14 days.
                                 Used by fraud_engine signal 11 (complaint burst).

  2. Order table
       + original_eta          — the ETA promised at order placement.
                                 Used by tracking templates to compute delay minutes.
       + delivery_proof        — Boolean; True when OTP or photo proof was captured.
                                 Used by fraud_engine signal 10 (delivery mismatch).
       + gps_anomaly           — Boolean; True when courier GPS track looks suspicious.
                                 Used by fraud_engine signal 10 (delivery mismatch).

  3. RefundClaim table
       + item_name             — which specific item the complaint is about (ITEM_SELECT flow).
       + item_price            — price of the affected item (for proportional coupon logic).
       + csat_rating           — 1/2/3 CSAT score collected after resolution (RATING state).
       + signals_fired         — JSONB; stores the fraud signals dict for audit/analytics.

  4. OrderItem table — unchanged, already correct.

  5. Alembic migration note at the bottom — run these after updating.
"""

from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import declarative_base

Base = declarative_base()


# ─────────────────────────────────────────────────────────────────────────────
# USER
# ─────────────────────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    user_id               = Column(String,  primary_key=True, index=True)
    phone_number          = Column(String,  unique=True, index=True, nullable=True)
                                # nullable=True for backward compat with existing rows;
                                # set NOT NULL in migration once backfilled.
    account_age_days      = Column(Integer, default=0)
    total_orders          = Column(Integer, default=0)
    refunds_30d           = Column(Integer, default=0)
    refunds_90d           = Column(Integer, default=0)
    refund_ratio          = Column(Float,   default=0.0)
                                # stored as decimal: 0.22 means 22% refund rate.
                                # fraud_engine multiplies by 100 before comparing.
    flagged               = Column(Integer, default=0)
                                # 0 = clean, 1 = flagged for abuse
    linked_account_flag   = Column(Boolean, default=False)
                                # True when same device/IP/payment found on 3+ accounts
    recent_complaint_count = Column(Integer, default=0)
                                # complaints filed in last 14 days; updated by background job


# ─────────────────────────────────────────────────────────────────────────────
# ORDER
# ─────────────────────────────────────────────────────────────────────────────

class Order(Base):
    __tablename__ = "orders"

    order_id        = Column(String,   primary_key=True, index=True)
    user_id         = Column(String,   ForeignKey("users.user_id"))
    item            = Column(String)
    restaurant      = Column(String)
    status          = Column(String)
                        # values: placed | preparing | on_the_way | delivered | cancelled
    courier         = Column(String,   nullable=True)
    eta_minutes     = Column(Integer,  nullable=True)   # current ETA (updated live)
    original_eta    = Column(Integer,  nullable=True)   # ETA at time of order placement
                                                         # delay = eta_minutes - original_eta
    progress        = Column(Integer,  nullable=True)   # 0–100 route completion %
    placed_at       = Column(DateTime, nullable=True)
    delivered_at    = Column(DateTime, nullable=True)
    amount          = Column(Float,    default=0.0)
    delivery_proof  = Column(Boolean,  default=True)
                        # False when no OTP or delivery photo was captured.
                        # Triggers fraud signal 10 (delivery_mismatch).
    gps_anomaly     = Column(Boolean,  default=False)
                        # True when courier GPS track is suspicious
                        # (e.g. marked delivered far from customer address).
                        # Set by courier tracking background job.


# ─────────────────────────────────────────────────────────────────────────────
# REFUND CLAIM
# ─────────────────────────────────────────────────────────────────────────────

class RefundClaim(Base):
    __tablename__ = "refund_claims"

    claim_id       = Column(Integer, primary_key=True, autoincrement=True)
    order_id       = Column(String,  ForeignKey("orders.order_id"))
    user_id        = Column(String,  ForeignKey("users.user_id"))
    issue_type     = Column(String)
                       # missing_item | wrong_order | spoilage | late_delivery |
                       # quantity_short | packaging_damaged | other
    description    = Column(Text,    nullable=True)
    image_hash     = Column(String,  nullable=True)  # pHash for duplicate detection
    image_meta     = Column(JSONB,   nullable=True)  # EXIF, MIME, size, flags
    item_name      = Column(String,  nullable=True)  # from ITEM_SELECT state
    item_price     = Column(Float,   nullable=True)  # price of the specific affected item
    risk_score     = Column(Integer, default=0)
    decision       = Column(String,  nullable=True)
                       # approve | deny | manual_review | escalate | pending
    signals_fired  = Column(JSONB,   nullable=True)
                       # dict of {signal_name: bool} from fraud_engine for analytics
    csat_rating    = Column(Integer, nullable=True)
                       # 1=Great | 2=Okay | 3=Poor; collected in RATING state
    created_at     = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
    )


# ─────────────────────────────────────────────────────────────────────────────
# ORDER ITEM  (unchanged)
# ─────────────────────────────────────────────────────────────────────────────

class OrderItem(Base):
    __tablename__ = "order_items"

    item_id   = Column(Integer, primary_key=True, autoincrement=True)
    order_id  = Column(String,  ForeignKey("orders.order_id"))
    name      = Column(String)
    quantity  = Column(Integer)
    price     = Column(Float)
    options   = Column(String, nullable=True)


# ─────────────────────────────────────────────────────────────────────────────
# ALEMBIC MIGRATION COMMANDS
# Run these after updating domain.py to apply schema changes to Neon PostgreSQL.
#
# 1. Generate a new migration:
#      alembic revision --autogenerate -m "add_missing_columns_phase1"
#
# 2. Review the generated file in infra/db_migrations/versions/
#    Make sure it only adds columns and does not DROP anything.
#
# 3. Apply the migration:
#      alembic upgrade head
#
# If you prefer raw SQL for Neon, run these manually in the Neon console:
#
#   ALTER TABLE users
#     ADD COLUMN IF NOT EXISTS phone_number           VARCHAR UNIQUE,
#     ADD COLUMN IF NOT EXISTS linked_account_flag    BOOLEAN DEFAULT FALSE,
#     ADD COLUMN IF NOT EXISTS recent_complaint_count INTEGER DEFAULT 0;
#
#   ALTER TABLE orders
#     ADD COLUMN IF NOT EXISTS original_eta    INTEGER,
#     ADD COLUMN IF NOT EXISTS delivery_proof  BOOLEAN DEFAULT TRUE,
#     ADD COLUMN IF NOT EXISTS gps_anomaly     BOOLEAN DEFAULT FALSE;
#
#   ALTER TABLE refund_claims
#     ADD COLUMN IF NOT EXISTS item_name      VARCHAR,
#     ADD COLUMN IF NOT EXISTS item_price     FLOAT,
#     ADD COLUMN IF NOT EXISTS csat_rating    INTEGER,
#     ADD COLUMN IF NOT EXISTS signals_fired  JSONB;
# ─────────────────────────────────────────────────────────────────────────────