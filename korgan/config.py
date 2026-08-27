from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    telegram_bot_token: str
    openai_api_key: str
    openai_model: str = "gpt-5.1"
    openai_vision_model: str = "gpt-5.1"
    openai_validation_model: str = "gpt-5.1"
    # Legal rules still come from Adilet. gov.kz / sud.gov.kz are allowed only
    # for official court-name / court-structure verification.
    official_legal_domains: str = "adilet.zan.kz,gov.kz,sud.gov.kz"
    max_case_documents: int = 12
    max_case_text_chars: int = 60000
    admin_telegram_ids: str = ""

    # Cost-control target. This does not weaken source-bound research, drafting,
    # validation or release gates; it prevents accidental opt-in to extra model
    # stages unless explicitly allowed.
    monthly_ai_budget_usd: float = 10.0
    token_budget_guard_enabled: bool = True
    allow_extra_ai_pipeline_calls: bool = False

    # Document payment gate.
    payments_enabled: bool = False
    kaspi_payment_url: str = ""
    kaspi_payment_recipient: str = "OpenCourt (KORGAN)"
    document_price_kzt: int = 1000

    # Consultation quota/payment gate. Kept separately from document payments so
    # the feature can be deployed dark and enabled only after persistent storage
    # is connected in Railway.
    consultation_limit_enabled: bool = False
    free_consultations_per_day: int = 5
    consultation_price_kzt: int = 1000
    database_url: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def legal_domains(self) -> list[str]:
        return [item.strip().lower() for item in self.official_legal_domains.split(",") if item.strip()]

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
