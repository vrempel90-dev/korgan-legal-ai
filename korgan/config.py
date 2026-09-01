from __future__ import annotations

from functools import lru_cache
from typing import Any

from pydantic import ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#: Типы, для которых пустая строка не является значением. Числа и флаги не
#: имеют написания «пустотой»: «» — это не ноль и не «выключено», это отсутствие
#: настройки. У строк наоборот: пустая строка — законное значение (так заданы
#: незаполненные ключи и реквизиты), поэтому их здесь нет.
_EMPTY_MEANS_UNSET = (int, float, bool)


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

    @field_validator("*", mode="before")
    @classmethod
    def _blank_numeric_env_means_unset(cls, value: Any, info: ValidationInfo) -> Any:
        """Пустая переменная окружения для числа — это «не задано», а не ошибка.

        Переменная, объявленная в Railway и оставленная без значения, приходит
        как пустая строка. Для числового поля pydantic считал это неверным
        вводом и валил построение Settings целиком — то есть весь сервис, из-за
        двух настроек, которые никто не собирался менять и которые имеют
        рабочие умолчания. Деплой при этом падал на predeploy-тестах, а
        production продолжал отдавать прошлый образ: снаружи это выглядело как
        потерянная связь с GitHub, а не как ошибка конфигурации.

        Пустая строка возвращается к объявленному здесь умолчанию только для
        чисел и флагов: у них нет написания «пустотой». Строковые настройки не
        трогаются — для них пустое значение осмысленно и означает именно пустое
        (незаданный ключ, незаполненный реквизит).

        Обязательное числовое поле остаётся ошибкой: подставлять число, которого
        никто не назвал, нельзя — оно ушло бы в расчёт как настоящее.
        """
        if not isinstance(value, str) or value.strip():
            return value
        field = cls.model_fields.get(info.field_name or "")
        if field is None or field.annotation not in _EMPTY_MEANS_UNSET:
            return value
        if field.is_required():
            return value
        return field.get_default(call_default_factory=True)

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

    # Роли моделей в порядке убывания важности: основная (исследование и
    # составление документа), зрение, валидация.
    _MODEL_ROLES = ("", "vision", "validation")

    @property
    def anthropic_model_for(self) -> dict[str, str]:
        """Какая модель Anthropic заменяет какую модель OpenAI.

        Вызывающий код передаёт имя модели OpenAI из настроек — извлечение,
        исследование и валидация ходят за разными именами. Соответствие
        задаётся здесь, чтобы роли сохранились при смене провайдера.

        Ключом служит имя модели OpenAI, а по умолчанию все три роли ходят за
        одним и тем же `gpt-5.1`. Значит словарь схлопывается в одну запись, и
        порядок решает, какая модель Anthropic достанется всем. Раньше побеждала
        последняя, то есть валидационная: `ANTHROPIC_MODEL=claude-opus-5` не
        давал никакого эффекта, а `ANTHROPIC_VALIDATION_MODEL=claude-haiku-4-5`,
        выставленный ради экономии на служебных вызовах, ронял на Haiku и
        составление иска. Обе ошибки были беззвучными. Теперь побеждает основная
        роль, а недостижимые из-за совпадения имён настройки перечисляет
        `unreachable_model_roles` — их показывает лог при сборке клиента.
        """
        mapping: dict[str, str] = {}
        for role in self._MODEL_ROLES:
            mapping.setdefault(self._openai_model_for_role(role), self._anthropic_model_for_role(role))
        return mapping

    def _openai_model_for_role(self, role: str) -> str:
        return getattr(self, f"openai_{role}_model" if role else "openai_model")

    def _anthropic_model_for_role(self, role: str) -> str:
        return getattr(self, f"anthropic_{role}_model" if role else "anthropic_model")

    @property
    def unreachable_model_roles(self) -> list[str]:
        """Роли, чья модель Anthropic задана, но никогда не будет выбрана.

        Роль различима только по имени модели OpenAI, с которым пришёл запрос.
        Если два имени совпали, вторая роль недостижима — и оператор, выставивший
        для неё отдельную модель, должен об этом узнать, а не гадать, почему
        настройка ничего не изменила.

        Сообщается только о том, что оператор задал сам: нетронутое умолчание
        роли недостижимо ровно так же, но жаловаться на него значило бы писать
        предупреждение в каждый обычный запуск, и настоящее сообщение потерялось
        бы среди шума.
        """
        unreachable: list[str] = []
        winners: dict[str, tuple[str, str]] = {}
        for role in self._MODEL_ROLES:
            name = role or "основная"
            field = f"anthropic_{role}_model" if role else "anthropic_model"
            openai_name = self._openai_model_for_role(role)
            anthropic_name = self._anthropic_model_for_role(role)
            winner_name, winner_model = winners.setdefault(openai_name, (name, anthropic_name))
            if winner_name == name or anthropic_name == winner_model:
                continue
            if field not in self.model_fields_set:
                continue
            unreachable.append(
                f"{name}: задана {anthropic_name}, но роль ходит за тем же "
                f"{openai_name}, что и роль «{winner_name}», поэтому будет "
                f"использована {winner_model}"
            )
        return unreachable

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
