from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    NEON_DATABASE_URL: str
    GEMINI_API_KEY: str
    FRONTEND_URL: str = "http://localhost:5173"
    
    FRAUD_THRESHOLD_AUTO_APPROVE: int = 40
    FRAUD_THRESHOLD_DENY: int = 60

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()