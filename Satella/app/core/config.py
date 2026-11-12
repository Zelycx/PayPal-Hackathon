from functools import lru_cache

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", env_ignore_empty=True, extra="ignore")

    app_env: str = "development"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    app_api_key: str = ""
    demo_data_enabled: bool = True
    database_url: str = "sqlite:///./ai_companion.db"
    groq_api_key: str = ""
    groq_chat_model: str = "qwen/qwen3.8-27b"
    groq_vision_model: str = "qwen/qwen3.8-27b"
    groq_transcription_model: str = "whisper-large-v3-turbo"
    groq_timeout_seconds: float = 30.0
    groq_temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    groq_max_completion_tokens: int | None = Field(default=None, ge=64, le=32768)
    groq_max_continuations: int = Field(default=2, ge=0, le=5)
    ai_personality: str = "ellie"
    max_chat_history_messages: int = Field(default=24, ge=2, le=100)
    max_tool_rounds: int = Field(default=4, ge=1, le=8)
    max_image_bytes: int = Field(default=8 * 1024 * 1024, ge=1024)
    max_audio_bytes: int = Field(default=20 * 1024 * 1024, ge=1024)
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    paypal_enabled: bool = False
    paypal_client_id: str = ""
    paypal_client_secret: str = ""
    paypal_environment: str = "sandbox"

    @field_validator("ai_personality")
    @classmethod
    def normalize_personality(cls, value: str) -> str:
        normalized = value.strip().casefold()
        return "ellie" if normalized == "ciel" else normalized

    @model_validator(mode="after")
    def require_production_auth(self) -> "Settings":
        if self.app_env.lower() == "production" and not self.app_api_key:
            raise ValueError("APP_API_KEY must be configured when APP_ENV=production")
        return self

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
