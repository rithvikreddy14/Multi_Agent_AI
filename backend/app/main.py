from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.api.routes_orders import router as orders_router
from app.api.routes_claims import router as claims_router

app = FastAPI(
    title="Nexus API",
    description="Multi-Agent AI Operations Platform - Phase 1",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(orders_router)
app.include_router(claims_router)

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "nexus-backend"}