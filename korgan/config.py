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

    # Claim -> live-lawyer WhatsApp handoff. These are deliberately optional so
    # production stays fail-closed until Meta Cloud API is configured.
    whatsapp_access_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_graph_api_version: str = ""
    whatsapp_review_template_name: str = ""
    whatsapp_review_template_language: str = "ru"
    whatsapp_lawyer_number: str = "77005000553"

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

    @property
    def whatsapp_review_ready(self) -> bool:
        return all(
            value.strip()
            for value in (
                self.whatsapp_access_token,
                self.whatsapp_phone_number_id,
                self.whatsapp_graph_api_version,
                self.whatsapp_review_template_name,
                self.whatsapp_lawyer_number,
            )
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
