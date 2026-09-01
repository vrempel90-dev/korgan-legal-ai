from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    telegram_bot_token: str
    openai_api_key: str
    openai_model: str = "gpt-5.1"
    openai_vision_model: str = "gpt-5.1"
    openai_validation_model: str = "gpt-5.1"

    # Anthropic — основной провайдер, OpenAI остаётся запасным. Ключ не
    # обязателен: без него `active_ai_provider` сам возвращает openai, поэтому
    # окружение без ANTHROPIC_API_KEY (в том числе CI) работает как раньше.
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5"
    anthropic_vision_model: str = "claude-sonnet-5"
    anthropic_validation_model: str = "claude-sonnet-5"
    # Проект иска целиком уходит в один структурированный ответ, поэтому предел
    # считается по самому длинному документу, а не по компактному research JSON.
    anthropic_max_output_tokens: int = 16000
    # auto | anthropic | openai. auto выбирает Anthropic при наличии ключа.
    ai_provider: str = "auto"
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
    # Fiscal merchant identity used by the deterministic receipt.kaspi.kz gate.
    # KASPI_SELLER_BIN is authoritative when configured. KASPI_RNM is retained
    # for diagnostics/additional validation and never weakens BIN/recipient checks.
    kaspi_seller_bin: str = ""
    kaspi_rnm: str = ""
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
    def active_ai_provider(self) -> str:
        """Провайдер, которым действительно пойдёт запрос.

        Выбор объявлен здесь, а не в сервисе, потому что от него зависят и
        клиент, и учёт стоимости, и то, что показывает /health. Ключ решает
        спор: просить Anthropic без ключа — это отказ вместо ответа, поэтому
        `auto` без ключа означает OpenAI, а не ошибку.
        """
        requested = self.ai_provider.strip().lower() or "auto"
        has_key = bool(self.anthropic_api_key.strip())
        if requested == "openai":
            return "openai"
        if requested == "anthropic":
            return "anthropic" if has_key else "openai"
        return "anthropic" if has_key else "openai"

    @property
    def anthropic_model_for(self) -> dict[str, str]:
        """Какая модель Anthropic заменяет какую модель OpenAI.

        Вызывающий код передаёт имя модели OpenAI из настроек — извлечение,
        исследование и валидация ходят за разными именами. Соответствие
        задаётся здесь, чтобы роли сохранились при смене провайдера.
        """
        return {
            self.openai_model: self.anthropic_model,
            self.openai_vision_model: self.anthropic_vision_model,
            self.openai_validation_model: self.anthropic_validation_model,
        }

    @property
    def legal_domains(self) -> list[str]:
        return [item.strip().lower() for item in self.official_legal_domains.split(",") if item.strip()]

    @property
    def payment_seller_bin(self) -> str:
        return self.kaspi_seller_bin.strip()

    @property
    def payment_rnm(self) -> str:
        return self.kaspi_rnm.strip()

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
