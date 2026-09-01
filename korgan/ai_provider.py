"""Выбор провайдера модели и откат на запасного.

Юридическому ядру всё равно, кто отвечает: оно спрашивает
`client.responses.create(...)` и разбирает результат. Здесь собирается тот
самый клиент — Anthropic как основной, OpenAI как запасной, — и решается, что
считать поводом для отката.

Поводом является отказ провайдера: сеть не ответила, вернулись 429 или 5xx,
ключ отозван. Поводом НЕ является `incomplete`. Это разные вещи, и смешивать
их нельзя: `incomplete` — это результат работающего провайдера, означающий
«структурного ответа нет», и повтор у другого провайдера превратил бы
сознательный отказ отвечать без источников в ещё одну попытку получить ответ
любой ценой. Fail-closed должен оставаться fail-closed у обоих.
"""

from __future__ import annotations

import logging
from typing import Any

from korgan.ai_cost import METER
from korgan.config import Settings

LOGGER = logging.getLogger(__name__)


class MeteredResponses:
    """Считает расход на каждом ответе модели.

    Обёртка стоит снаружи выбора провайдера, а не внутри одной из веток: через
    неё проходит и Anthropic, и OpenAI, и запасной вызов после отката. Внутри
    ветки часть расхода осталась бы неучтённой — а неучтённый расход и есть то,
    из-за чего бюджет кончается раньше срока.
    """

    def __init__(self, inner: Any, meter: Any = METER):
        self._inner = inner
        self._meter = meter

    async def create(self, **kwargs: Any) -> Any:
        response = await self._inner.create(**kwargs)
        # Имя берётся из ответа: при работе через Anthropic вызывающий код
        # по-прежнему передаёт имя модели OpenAI, и учёт по нему считал бы
        # расход по чужому тарифу.
        model = str(getattr(response, "model", "") or kwargs.get("model") or "")
        self._meter.record(model, response)
        return response


class MeteredClient:
    def __init__(self, inner: Any, meter: Any = METER):
        self.responses = MeteredResponses(inner.responses, meter)


class FallbackResponses:
    """Основной провайдер с одной попыткой у запасного при его отказе."""

    def __init__(self, primary: Any, secondary: Any, *, primary_name: str, secondary_name: str):
        self._primary = primary
        self._secondary = secondary
        self._primary_name = primary_name
        self._secondary_name = secondary_name

    async def create(self, **kwargs: Any) -> Any:
        try:
            return await self._primary.create(**kwargs)
        except Exception as error:  # noqa: BLE001 — откат должен пережить любой отказ провайдера
            LOGGER.warning(
                "KORGAN AI provider %s failed (%s: %s) — retrying via %s",
                self._primary_name,
                type(error).__name__,
                error,
                self._secondary_name,
            )
            return await self._secondary.create(**kwargs)


class FallbackClient:
    """Клиент с полем `responses`, как у AsyncOpenAI."""

    def __init__(self, primary: Any, secondary: Any, *, primary_name: str, secondary_name: str):
        self.responses = FallbackResponses(
            primary.responses,
            secondary.responses,
            primary_name=primary_name,
            secondary_name=secondary_name,
        )


def build_legal_client(settings: Settings) -> tuple[Any, str]:
    """Собирает клиента для юридического сервиса.

    Возвращает пару «клиент, имя активного провайдера». Имя нужно не для
    красоты: его показывает /health, и по нему видно, что именно отвечало
    клиенту, — иначе смена провайдера была бы невидимой в проде.
    """
    from openai import AsyncOpenAI

    METER.budget_usd = settings.monthly_ai_budget_usd
    openai_client = AsyncOpenAI(api_key=settings.openai_api_key)
    if settings.active_ai_provider != "anthropic":
        return MeteredClient(openai_client), "openai"

    try:
        from anthropic import AsyncAnthropic

        from korgan.anthropic_responses import AnthropicResponsesClient
    except ImportError as error:
        # Пакет не поставлен — это состояние окружения, а не выбор оператора.
        # Отказать в консультации из-за него нельзя, поэтому работает запасной.
        LOGGER.warning("KORGAN anthropic SDK unavailable (%s) — using OpenAI", error)
        return MeteredClient(openai_client), "openai"

    # Роль различается только по имени модели OpenAI, с которым пришёл запрос.
    # Если оператор задал отдельную модель для роли, чьё имя совпало с основной,
    # настройка не сработает — и об этом надо сказать вслух. Молчание здесь
    # означало бы, что выставленный ради экономии дешёвый валидатор просто не
    # применился, а счёт продолжал расти по тарифу основной модели.
    for warning in settings.unreachable_model_roles:
        LOGGER.warning("KORGAN model role is unreachable — %s", warning)

    anthropic_client = AnthropicResponsesClient(
        AsyncAnthropic(api_key=settings.anthropic_api_key),
        model_map=settings.anthropic_model_for,
        default_model=settings.anthropic_model,
        max_tokens=settings.anthropic_max_output_tokens,
    )
    return (
        MeteredClient(
            FallbackClient(
                anthropic_client,
                openai_client,
                primary_name="anthropic",
                secondary_name="openai",
            )
        ),
        "anthropic",
    )
