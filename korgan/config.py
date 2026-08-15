from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    telegram_bot_token: str
    openai_api_key: str
    openai_model: str = "gpt-5.6-terra"
    openai_embedding_model: str = "text-embedding-3-small"
    pinecone_api_key: str
    pinecone_index_name: str = "korgan-legal-kz"
    rag_top_k: int = 8
    rag_min_score: float = 0.45
    admin_telegram_ids: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def admin_ids(self) -> set[int]:
        result: set[int] = set()
        for value in self.admin_telegram_ids.split(","):
            value = value.strip()
            if value:
                result.add(int(value))
        return result


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
