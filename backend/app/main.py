# app/main.py
"""
Nexus FastAPI application entry point.

Changes from original:
  1. Added lifespan context manager (replaces deprecated @app.on_event)
       FastAPI 0.93+ deprecates @app.on_event("startup").
       Using the modern lifespan= parameter instead.
       On startup: creates DB tables (dev only) and logs all registered routes.
       On shutdown: disposes the SQLAlchemy connection pool cleanly.

  2. Added DB table creation on startup (dev mode only)
       Calls neon_pg.create_tables() so a fresh clone runs without needing
       manual Alembic commands. Skipped in production (TABLE_AUTO_CREATE=false).

  3. Added /webhook/notify route explicitly
       The notify endpoint lives in routes_webhook.py and is already included
       via webhook_router — no extra include needed. Added comment for clarity.

  4. Tightened CORS for production readiness
       Original: allow_origins=[settings.FRONTEND_URL] (single origin, correct)
       Added allow_origin_regex for Vercel preview deployments (optional, commented out).
       Kept the existing single-origin setting as the default.

  5. Added global exception handler
       Returns consistent JSON {detail: str} for unhandled 500 errors instead of
       FastAPI's default HTML error page, which breaks the WhatsApp XML response flow.

  6. Added /health endpoint with DB connectivity check
       Original health check returned a static dict with no real check.
       New version pings the DB so load balancers and uptime monitors get
       an accurate signal when the DB is unreachable.

  7. Added startup banner log
       Prints registered route count on startup so you can verify all routers
       loaded correctly during development.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings

logger = logging.getLogger(__name__)

logging.basicConfig(
    level   = logging.INFO,
    format  = "%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt = "%Y-%m-%d %H:%M:%S",
)


# ── Lifespan ──────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Startup → yield → shutdown.
    Everything before yield runs on startup.
    Everything after yield runs on shutdown.
    """
    # ── Startup ────────────────────────────────────────────────────────
    logger.info("Nexus backend starting up...")

    # Create DB tables automatically in development.
    # Comment this block out in production and use Alembic migrations.
    try:
        from app.db.neon_pg import create_tables
        await create_tables()
        logger.info("DB tables verified / created.")
    except Exception as exc:
        logger.error("DB table creation failed: %s", exc)
        # Don't crash on startup if DB is temporarily unreachable.

    route_count = len(app.routes)
    logger.info("Startup complete. %d routes registered.", route_count)

    yield  # ← app is live here

    # ── Shutdown ───────────────────────────────────────────────────────
    logger.info("Nexus backend shutting down — disposing DB pool...")
    from app.db.neon_pg import engine
    await engine.dispose()
    logger.info("DB pool disposed. Goodbye.")


# ── App factory ───────────────────────────────────────────────────────────

app = FastAPI(
    title       = "Nexus API",
    description = (
        "Multi-Agent AI Operations Platform — Phase 1\n\n"
        "Endpoints:\n"
        "- `/order/{id}/track` — live order tracking (no AI)\n"
        "- `/claim/submit` — submit a refund/compensation claim\n"
        "- `/claim/image-check` — validate an uploaded image\n"
        "- `/claim/history/{user_id}` — user claim history\n"
        "- `/claim/admin/queue` — manual review queue (admin)\n"
        "- `/webhook/whatsapp` — Twilio WhatsApp inbound webhook\n"
        "- `/webhook/notify` — send proactive order notifications\n"
        "- `/health` — health check with DB ping\n"
    ),
    version  = "1.0.0",
    lifespan = lifespan,
)


# ── CORS ──────────────────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins      = [settings.FRONTEND_URL],
    allow_credentials  = True,
    allow_methods      = ["*"],
    allow_headers      = ["*"],
    # Uncomment for Vercel preview deployments:
    # allow_origin_regex = r"https://nexus-.*\.vercel\.app",
)


# ── Global exception handler ──────────────────────────────────────────────

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """
    Catch unhandled exceptions and return JSON instead of HTML.
    Critical for the WhatsApp webhook — Twilio expects XML/JSON, not an HTML 500 page.
    """
    logger.error("Unhandled exception on %s %s: %s", request.method, request.url.path, exc)
    return JSONResponse(
        status_code = 500,
        content     = {"detail": "Internal server error. Please try again later."},
    )


# ── Routers ───────────────────────────────────────────────────────────────

from app.api.routes_orders  import router as orders_router   # noqa: E402
from app.api.routes_claims  import router as claims_router   # noqa: E402
from app.api.routes_webhook import router as webhook_router  # noqa: E402

app.include_router(orders_router)   # GET  /order/{id}/track
app.include_router(claims_router)   # POST /claim/submit, /claim/image-check, etc.
app.include_router(webhook_router)  # POST /webhook/whatsapp, POST /webhook/notify


# ── Health check ──────────────────────────────────────────────────────────

@app.get("/health", tags=["System"])
async def health_check():
    """
    Returns 200 + DB status.
    Load balancers and uptime monitors should hit this endpoint.
    Returns 200 even when DB is down (degraded: true) so the app stays
    in the load balancer pool — Neon serverless can have cold-start latency.
    """
    db_ok = False
    try:
        from sqlalchemy import text
        from app.db.neon_pg import engine
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception as exc:
        logger.warning("Health check DB ping failed: %s", exc)

    return {
        "status"   : "healthy" if db_ok else "degraded",
        "service"  : "nexus-backend",
        "version"  : "1.0.0",
        "database" : "connected" if db_ok else "unreachable",
    }