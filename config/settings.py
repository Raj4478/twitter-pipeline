"""Settings — Twitter/Telegram Pipeline"""

from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    # ── LLM ────────────────────────────────────────────────────────────
    groq_api_key: str = Field(default="")
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_model: str = "llama-3.3-70b-versatile"
    gemini_api_key: str = Field(default="")
    gemini_model: str = "gemini-2.5-flash-lite"
    llm_timeout_seconds: int = 30
    active_llm: str = "gemini"

    # ── Twitter API v2 (kept for future use) ───────────────────────────
    twitter_api_key: str = Field(default="")
    twitter_api_secret: str = Field(default="")
    twitter_access_token: str = Field(default="")
    twitter_access_token_secret: str = Field(default="")
    twitter_bearer_token: str = Field(default="")

    # ── Telegram ───────────────────────────────────────────────────────
    telegram_bot_token: str = Field(default="")
    telegram_allowed_user_id: str = Field(default="")   # personal chat for notifications
    telegram_channel_id: str = Field(default="")        # channel to post threads e.g. @mychannel

    def active_providers(self) -> list[str]:
        providers = []
        if self.gemini_api_key:
            providers.append("gemini")
        if self.groq_api_key:
            providers.append("groq")
        return providers or ["groq"]

    class Config:
        env_file = ".env"
        extra = "ignore"
