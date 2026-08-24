from __future__ import annotations

from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


_GPT56_ROLE_MODELS = {
    "openai_model": "gpt-5.6-sol",
    "openai_validation_model": "gpt-5.6-terra",
    "openai_vision_model": "gpt-5.6-luna",
}


class Settings(BaseSettings):
    telegram_bot_token: str
    openai_api_key: str

    # GPT-5.6 role routing. Legal reasoning/final drafting stays on Sol;
    # validation/review uses Terra; extraction/vision uses Luna.  These values
    # are deliberately locked so a stale Railway variable cannot silently move
    # production back to GPT-5.1 or to a model outside the 5.6 family.
    openai_model: str = _GPT56_ROLE_MODELS["openai_model"]
    openai_vision_model: str = _GPT56_ROLE_MODELS["openai_vision_model"]
    openai_validation_model: str = _GPT56_ROLE_MODELS["openai_validation_model"]

    # Legal rules still come from Adilet. gov.kz / sud.gov.kz are allowed only
    # for official court-name / court-structure verification.
    official_legal_domains: str = "adilet.zan.kz,gov.kz,sud.gov.kz"
    max_case_documents: int = 12
    max_case_text_chars: int = 60000
    admin_telegram_ids: str = ""

    # Cost-control target: $62 / 4 months = $15.50/month.  The daily target is
    # intentionally slightly below the 31-day pro-rata ceiling.  This does not
    # weaken source-bound research, drafting, validation or release gates; it
    # prevents accidental opt-in to extra model stages unless explicitly
    # allowed.
    monthly_ai_budget_usd: float = 15.50
    daily_ai_budget_usd: float = 0.50
    token_budget_guard_enabled: bool = True
    allow_extra_ai_pipeline_calls: bool = False

    # Document payment gate.
    payments_enabled: bool = False
    kaspi_payment_url: str = ""
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

    @model_validator(mode="after")
    def lock_gpt56_model_roles(self) -> "Settings":
        for field_name, expected in _GPT56_ROLE_MODELS.items():
            actual = getattr(self, field_name)
            if actual != expected:
                raise ValueError(
                    f"{field_name} must be {expected}; refusing model drift to {actual!r}"
                )
        return self

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
