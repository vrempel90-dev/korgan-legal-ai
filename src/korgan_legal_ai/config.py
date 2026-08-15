from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str | None = None
    openai_api_key: str | None = None
    korgan_model_fact_lock: str = "gpt-5-mini"
    korgan_model_router: str = "gpt-5-mini"
    korgan_model_draft: str = "gpt-5.1"
    korgan_model_qa: str = "gpt-5.1"
    korgan_embedding_model: str = "text-embedding-3-large"
    korgan_default_language: str = "ru"

    telegram_bot_token: str | None = None
    telegram_privacy_version: str = "2026-08-15"
    telegram_poll_timeout_seconds: int = 30
    telegram_request_timeout_seconds: float = 45.0
    telegram_session_ttl_seconds: int = 86400
    telegram_max_sessions: int = 5000
    telegram_max_case_chars: int = 16000
