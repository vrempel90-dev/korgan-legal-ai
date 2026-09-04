"""Инварианты устойчивости пути к модели: повтор, откат и молчание об ошибке.

Три свойства, которые в проде отличают «клиент подождал лишние секунды» от
«клиент заплатил и не получил документ», и ни одно из них не видно в обычном
тесте бизнес-логики:

1. транзиентный отказ провайдера (429, 5xx, обрыв соединения) повторяется
   клиентом SDK, а не превращается в отказ с первой попытки;
2. отказ основного провайдера уводит запрос на запасного;
3. текст ошибки провайдера клиенту не показывается — ни ключ, ни адрес
   endpoint, ни путь файла в трассировке.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from korgan.ai_provider import FallbackClient, build_openai_client
from korgan.config import Settings
from korgan.miniapp_generation_jobs import GenerationFailure, _client_detail


def test_openai_client_keeps_transient_retries() -> None:
    """Ретраи SDK не отключены: 429 и 5xx повторяются, а не роняют генерацию."""
    client = build_openai_client(Settings())

    assert client.max_retries >= 2


def test_anthropic_client_keeps_transient_retries() -> None:
    from anthropic import AsyncAnthropic

    assert AsyncAnthropic(api_key="test").max_retries >= 2


def test_transient_primary_failure_is_served_by_the_fallback() -> None:
    calls: list[str] = []

    class _Overloaded:
        async def create(self, **_: object) -> object:
            calls.append("primary")
            raise RuntimeError("Error code: 529 - overloaded_error")

    class _Working:
        async def create(self, **kwargs: object) -> object:
            calls.append("secondary")
            return SimpleNamespace(output_text="{}", model="gpt-5.1")

    client = FallbackClient(
        SimpleNamespace(responses=_Overloaded()),
        SimpleNamespace(responses=_Working()),
        primary_name="anthropic",
        secondary_name="openai",
    )

    result = asyncio.run(client.responses.create(model="gpt-5.1", input="вопрос"))

    assert calls == ["primary", "secondary"]
    assert result.output_text == "{}"


def test_provider_error_text_never_reaches_the_client() -> None:
    leaky = RuntimeError(
        "Error code: 401 - {'error': {'message': 'invalid x-api-key sk-ant-api03-secret'}} "
        "at https://api.anthropic.com/v1/messages (korgan/robust_production_legal.py:263)"
    )

    detail = _client_detail(leaky)

    for fragment in ("sk-ant", "api.anthropic", "korgan/", "401", "x-api-key"):
        assert fragment not in detail
    assert "повтор" in detail.lower()


def test_message_written_for_the_client_is_kept_as_written() -> None:
    """Отказ, сформулированный для человека, не подменяется общей фразой."""
    detail = _client_detail(GenerationFailure("В материалах не указан срок исполнения обязательства."))

    assert detail == "В материалах не указан срок исполнения обязательства."
