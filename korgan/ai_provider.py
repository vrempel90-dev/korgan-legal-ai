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

from korgan.config import Settings

LOGGER = logging.getLogger(__name__)


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

    openai_client = AsyncOpenAI(api_key=settings.openai_api_key)
    if settings.active_ai_provider != "anthropic":
        return openai_client, "openai"

    try:
        from anthropic import AsyncAnthropic

        from korgan.anthropic_responses import AnthropicResponsesClient
    except ImportError as error:
        # Пакет не поставлен — это состояние окружения, а не выбор оператора.
        # Отказать в консультации из-за него нельзя, поэтому работает запасной.
        LOGGER.warning("KORGAN anthropic SDK unavailable (%s) — using OpenAI", error)
        return openai_client, "openai"

    anthropic_client = AnthropicResponsesClient(
        AsyncAnthropic(api_key=settings.anthropic_api_key),
        model_map=settings.anthropic_model_for,
        default_model=settings.anthropic_model,
        max_tokens=settings.anthropic_max_output_tokens,
    )
    return (
        FallbackClient(
            anthropic_client,
            openai_client,
            primary_name="anthropic",
            secondary_name="openai",
        ),
        "anthropic",
    )
