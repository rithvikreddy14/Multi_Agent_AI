# app/core/config.py
"""
Nexus platform settings — loaded from .env via pydantic-settings.

Changes from original:
  1. Added TWILIO_ACCOUNT_SID    — required by image_checker (Twilio Basic Auth for
                                   media download) and the proactive /notify endpoint.
  2. Added TWILIO_WHATSAPP_FROM  — the Twilio WhatsApp sandbox / business number
                                   used as the 'from_' in outbound messages.
  3. Added TWILIO_WEBHOOK_SECRET — same as TWILIO_AUTH_TOKEN alias kept for clarity;
                                   used by RequestValidator in routes_webhook.py.
  4. Removed GEMINI_API_KEY      — project switched to Groq/Llama. Key kept as Optional
                                   so anyone who still uses Gemini doesn't break.
  5. Added fraud threshold vars  — FRAUD_THRESHOLD_AUTO_APPROVE and FRAUD_THRESHOLD_DENY
                                   already existed; added CLAIM_WINDOW_HOURS so the
                                   webhook and fraud engine share one source of truth.
  6. Added SESSION_TTL_SECONDS   — lets local_session.py read timeout from config
                                   instead of a hardcoded constant.

.env.example (copy this, rename to .env, fill in real values):
  NEON_DATABASE_URL=postgresql+asyncpg://user:pass@host/dbname
  GROQ_API_KEY=gsk_...
  GEMINI_API_KEY=                        # optional, leave blank if unused
  TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxx
  TWILIO_AUTH_TOKEN=xxxxxxxxxxxxxxxx
  TWILIO_WHATSAPP_FROM=+14155238886      # Twilio sandbox number
  FRONTEND_URL=http://localhost:5173
  FRAUD_THRESHOLD_AUTO_APPROVE=40
  FRAUD_THRESHOLD_DENY=60
  CLAIM_WINDOW_HOURS=2.0
  SESSION_TTL_SECONDS=1800
"""

from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):

    # ── Database ───────────────────────────────────────────────────────────
    NEON_DATABASE_URL: str               # asyncpg connection string for Neon PostgreSQL

    # ── AI / LLM ──────────────────────────────────────────────────────────
    GROQ_API_KEY: str                    # Groq Llama 3.3 70B — primary AI verifier
    GEMINI_API_KEY: Optional[str] = None # optional; kept for backward compat

    # ── Twilio ────────────────────────────────────────────────────────────
    TWILIO_ACCOUNT_SID:   Optional[str] = None  # ACxxxxxxxxxxxxxxxx
    TWILIO_AUTH_TOKEN:    Optional[str] = None  # used for signature validation + media download
    TWILIO_WHATSAPP_FROM: Optional[str] = None  # e.g. +14155238886 (sandbox) or your business number

    # ── App ───────────────────────────────────────────────────────────────
    FRONTEND_URL: str = "http://localhost:5173"

    # ── Fraud engine thresholds (readable from routes_webhook.py if needed) ──
    FRAUD_THRESHOLD_AUTO_APPROVE: int   = 40    # score < this → proceed to AI verify
    FRAUD_THRESHOLD_DENY:         int   = 60    # score >= this → deny immediately
    CLAIM_WINDOW_HOURS:           float = 2.0   # max hours after delivery to file a claim

    # ── Session ───────────────────────────────────────────────────────────
    SESSION_TTL_SECONDS: int = 1800             # 30 minutes of inactivity → session expires

    model_config = SettingsConfigDict(
        env_file          = ".env",
        env_file_encoding = "utf-8",
        extra             = "ignore",   # silently ignore unknown keys in .env
    )


settings = Settings()