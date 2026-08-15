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
