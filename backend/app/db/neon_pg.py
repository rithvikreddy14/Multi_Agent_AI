# app/db/neon_pg.py
"""
Async SQLAlchemy engine + session factory for Neon PostgreSQL.

Changes from original:
  1. Added connect_args with ssl="require"
       Neon is a serverless Postgres — it enforces TLS on all connections.
       Without this, asyncpg raises "SSL connection has been closed unexpectedly"
       in production even though local dev sometimes works without it.

  2. Removed pool_size=20 / max_overflow=10 for Neon serverless
       Neon's serverless driver uses HTTP-based connection pooling (Neon proxy).
       Setting a large SQLAlchemy pool against a serverless endpoint wastes
       connections and can exhaust the Neon free-tier connection limit (10).
       Replaced with pool_size=5, max_overflow=5 which is safe for Phase 1.
       Upgrade these values when moving to Neon's dedicated compute tier.

  3. Added pool_pre_ping=True
       Neon serverless endpoints go to sleep after inactivity. pool_pre_ping
       sends a cheap "SELECT 1" before handing a connection to a request,
       preventing "connection closed" errors after idle periods.

  4. Added create_tables() startup helper
       Called from main.py lifespan. Creates all ORM tables on first run
       so you don't need to run Alembic manually during development.
       In production, remove this and use Alembic migrations only.

  5. get_db() unchanged in signature — all callers continue to work.
"""

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings

# ── Engine ────────────────────────────────────────────────────────────────
engine = create_async_engine(
    settings.NEON_DATABASE_URL,
    echo=False,
    pool_size=5,
    max_overflow=5,
    pool_recycle=1800,      # recycle connections every 30 min
    pool_pre_ping=True,     # test connection before use (handles Neon cold starts)
    connect_args={
        "ssl": "require",   # Neon enforces TLS — required in production
    },
)

# ── Session factory ───────────────────────────────────────────────────────
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


# ── FastAPI dependency ────────────────────────────────────────────────────
async def get_db():
    """
    Yield an AsyncSession for a single request.
    Session is closed whether or not an exception occurs.
    Commit is the caller's responsibility.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


# ── Dev / startup helper ──────────────────────────────────────────────────
async def create_tables() -> None:
    """
    Create all ORM-defined tables in the database if they don't exist.
    Safe to call on every startup — uses CREATE TABLE IF NOT EXISTS internally.

    Usage (in main.py lifespan):
        from app.db.neon_pg import create_tables
        await create_tables()

    Remove in production and rely on Alembic migrations instead.
    """
    from app.models.domain import Base  # local import to avoid circular at module level

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)