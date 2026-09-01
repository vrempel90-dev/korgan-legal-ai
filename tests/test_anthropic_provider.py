"""Anthropic отвечает под тем же контрактом, что и Responses API.

Юридическое ядро читает ответ двумя разными способами: `_annotation_urls` в
openai_legal.py ходит по атрибутам, `_actual_response_urls` в verified_openai.py
— по `model_dump()`. Оба используются в проде на одних и тех же ответах, и
расхождение между ними означало бы, что число подтверждённых источников зависит
от того, какой модуль спросил. Поэтому обе дороги проверяются здесь на одном
ответе адаптера.
"""

from __future__ import annotations

import asyncio
import json
from functools import wraps
from types import SimpleNamespace

import pytest

from korgan.ai_provider import FallbackClient, FallbackResponses, MeteredClient, build_legal_client
from korgan.anthropic_responses import WEB_SEARCH_TOOL, AnthropicResponsesClient
from korgan.config import Settings
from korgan.openai_legal import OpenAILegalService
from korgan.verified_openai import _actual_response_urls

def _sync(test):
    """Асинхронный тест под синхронным pytest — как в остальных тестах пакета."""

    @wraps(test)
    def run(*args: object, **kwargs: object) -> None:
        asyncio.run(test(*args, **kwargs))

    return run


SCHEMA = {
    "type": "object",
    "properties": {"applicable_law": {"type": "array", "items": {"type": "string"}}},
    "required": ["applicable_law"],
    "additionalProperties": False,
}


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "telegram_bot_token": "test-token",
        "openai_api_key": "test-key",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


class _FakeMessages:
    """Записывает запрос и отдаёт заранее собранный ответ Messages API."""

    def __init__(self, message: object):
        self.message = message
        self.request: dict[str, object] = {}

    async def create(self, **kwargs: object) -> object:
        self.request = kwargs
        return self.message


def _client(message: object, **overrides: object) -> tuple[AnthropicResponsesClient, _FakeMessages]:
    messages = _FakeMessages(message)
    settings = _settings(anthropic_api_key="anthropic-key", **overrides)
    client = AnthropicResponsesClient(
        SimpleNamespace(messages=messages),
        model_map=settings.anthropic_model_for,
        default_model=settings.anthropic_model,
        max_tokens=settings.anthropic_max_output_tokens,
    )
    return client, messages


def _tool_use(payload: dict[str, object], name: str = "korgan_legal_research") -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", name=name, input=payload)


def _message(content: list[object], stop_reason: str = "tool_use") -> SimpleNamespace:
    return SimpleNamespace(
        id="msg_1",
        model="claude-sonnet-5",
        content=content,
        stop_reason=stop_reason,
        usage=SimpleNamespace(input_tokens=120, output_tokens=340),
    )


# --- выбор провайдера ------------------------------------------------------

@pytest.mark.parametrize(
    ("requested", "key", "expected"),
    [
        ("auto", "anthropic-key", "anthropic"),
        ("auto", "", "openai"),
        ("anthropic", "anthropic-key", "anthropic"),
        # Просить Anthropic без ключа — это отказ вместо ответа.
        ("anthropic", "", "openai"),
        ("openai", "anthropic-key", "openai"),
    ],
)
def test_active_provider_follows_key_and_request(requested: str, key: str, expected: str) -> None:
    settings = _settings(ai_provider=requested, anthropic_api_key=key)
    assert settings.active_ai_provider == expected


def test_service_without_anthropic_key_keeps_openai() -> None:
    service = OpenAILegalService(_settings())
    assert service.ai_provider == "openai"
    assert not isinstance(service.client.responses._inner, FallbackResponses)


def test_service_with_anthropic_key_gets_fallback_client() -> None:
    client, provider = build_legal_client(_settings(anthropic_api_key="anthropic-key"))
    assert provider == "anthropic"
    assert isinstance(client.responses._inner, FallbackResponses)


def test_both_providers_are_metered() -> None:
    """Учёт расхода стоит снаружи выбора провайдера, а не в одной из веток."""
    with_anthropic, _ = build_legal_client(_settings(anthropic_api_key="anthropic-key"))
    without, _ = build_legal_client(_settings())
    assert isinstance(with_anthropic, MeteredClient)
    assert isinstance(without, MeteredClient)


def test_roles_of_models_survive_provider_switch() -> None:
    settings = _settings(
        anthropic_api_key="anthropic-key",
        openai_vision_model="gpt-5.1-vision",
        anthropic_vision_model="claude-vision",
    )
    assert settings.anthropic_model_for["gpt-5.1-vision"] == "claude-vision"
    # Различающиеся имена OpenAI — роли достижимы, жаловаться не на что.
    assert settings.unreachable_model_roles == []


def test_main_model_wins_when_openai_names_coincide() -> None:
    """`ANTHROPIC_MODEL` обязан решать, когда все роли ходят за одним именем.

    По умолчанию openai_model, openai_vision_model и openai_validation_model
    равны `gpt-5.1`, поэтому словарь ролей схлопывается в одну запись. Раньше
    побеждала последняя, валидационная: заданная основная модель не давала
    никакого эффекта, а дешёвый валидатор ронял на себя и составление иска.
    """
    settings = _settings(
        anthropic_api_key="anthropic-key",
        anthropic_model="claude-opus-5",
        anthropic_validation_model="claude-haiku-4-5",
    )
    assert settings.anthropic_model_for["gpt-5.1"] == "claude-opus-5"


def test_unreachable_role_is_named_rather_than_ignored() -> None:
    """Настройка, которая ничего не изменит, должна сказать об этом."""
    settings = _settings(
        anthropic_api_key="anthropic-key",
        anthropic_model="claude-opus-5",
        anthropic_validation_model="claude-haiku-4-5",
    )
    unreachable = settings.unreachable_model_roles
    assert len(unreachable) == 1
    assert "validation" in unreachable[0]
    assert "claude-haiku-4-5" in unreachable[0]
    assert "claude-opus-5" in unreachable[0]


def test_identical_role_models_are_not_reported_as_a_problem() -> None:
    """Совпадение имён само по себе не проблема — проблема лишь потерянная настройка."""
    assert _settings(anthropic_api_key="anthropic-key").unreachable_model_roles == []


# --- перевод запроса -------------------------------------------------------

@_sync
async def test_schema_becomes_a_forced_tool_call() -> None:
    client, messages = _client(_message([_tool_use({"applicable_law": ["ГК РК 715"]})]))

    response = await client.responses.create(
        model="gpt-5.1",
        instructions="Ты юридический исследователь",
        input=[{"role": "user", "content": [{"type": "input_text", "text": "вопрос"}]}],
        text={"format": {"type": "json_schema", "name": "korgan_legal_research", "schema": SCHEMA, "strict": True}},
        store=False,
    )

    assert messages.request["tool_choice"] == {"type": "tool", "name": "korgan_legal_research"}
    assert messages.request["tools"][0]["input_schema"] == SCHEMA
    assert messages.request["system"] == "Ты юридический исследователь"
    assert messages.request["model"] == "claude-sonnet-5"
    assert json.loads(response.output_text) == {"applicable_law": ["ГК РК 715"]}
    assert response.status == "completed"


@_sync
async def test_allowed_domains_survive_the_translation() -> None:
    """Список доменов — это и есть обещание «только официальные источники»."""
    client, messages = _client(_message([_tool_use({"applicable_law": []})]))

    await client.responses.create(
        model="gpt-5.1",
        instructions="",
        input="вопрос",
        text={"format": {"type": "json_schema", "name": "korgan_legal_research", "schema": SCHEMA}},
        tools=[{
            "type": "web_search",
            "filters": {"allowed_domains": ["adilet.zan.kz", "gov.kz"]},
            "search_context_size": "high",
        }],
        tool_choice="required",
    )

    search = [tool for tool in messages.request["tools"] if tool.get("type") == WEB_SEARCH_TOOL]
    assert len(search) == 1
    assert search[0]["allowed_domains"] == ["adilet.zan.kz", "gov.kz"]
    # Обязательный вызов схемы отключил бы поиск, поэтому выбор остаётся за моделью.
    assert messages.request["tool_choice"] == {"type": "auto"}
    assert "korgan_legal_research" in messages.request["system"]


@_sync
async def test_materials_are_sent_as_files_not_links() -> None:
    client, messages = _client(_message([_tool_use({"applicable_law": []})]))

    await client.responses.create(
        model="gpt-5.1",
        instructions="",
        input=[{
            "role": "user",
            "content": [
                {"type": "input_text", "text": "извлеки факты"},
                {"type": "input_image", "image_url": "data:image/png;base64,QUJD", "detail": "high"},
                {"type": "input_file", "filename": "claim.pdf", "file_data": "REVG"},
            ],
        }],
        text={"format": {"type": "json_schema", "name": "korgan_legal_research", "schema": SCHEMA}},
    )

    blocks = messages.request["messages"][0]["content"]
    assert blocks[0] == {"type": "text", "text": "извлеки факты"}
    assert blocks[1]["source"] == {"type": "base64", "media_type": "image/png", "data": "QUJD"}
    assert blocks[2]["source"] == {"type": "base64", "media_type": "application/pdf", "data": "REVG"}


@_sync
async def test_remote_image_is_refused_rather_than_dropped() -> None:
    client, _ = _client(_message([_tool_use({"applicable_law": []})]))

    with pytest.raises(ValueError):
        await client.responses.create(
            model="gpt-5.1",
            instructions="",
            input=[{"role": "user", "content": [{"type": "input_image", "image_url": "https://example.kz/a.png"}]}],
            text={"format": {"type": "json_schema", "name": "korgan_legal_research", "schema": SCHEMA}},
        )


@_sync
@pytest.mark.parametrize(
    ("requested", "expected"),
    # «none» у Anthropic нет, самый экономный уровень — low.
    [("none", "low"), ("low", "low"), ("medium", "medium"), ("high", "high")],
)
async def test_reasoning_effort_becomes_output_config(requested: str, expected: str) -> None:
    client, messages = _client(_message([_tool_use({"applicable_law": []})]))

    await client.responses.create(
        model="gpt-5.1",
        instructions="",
        input="вопрос",
        text={"format": {"type": "json_schema", "name": "korgan_legal_research", "schema": SCHEMA}},
        reasoning={"effort": requested},
    )

    assert messages.request["output_config"] == {"effort": expected}


@_sync
async def test_service_calls_do_not_silently_get_maximum_effort() -> None:
    """`effort: none` на служебном вызове обязан доехать до Anthropic.

    Умолчание Anthropic — `high`. Потерянный при переводе параметр не сломал бы
    ни один тест и не выдал бы ошибки: он просто поднял бы каждое извлечение,
    исследование и валидацию до самого дорогого уровня и незаметно сжёг бюджет.
    """
    from korgan.pro_document_quality import reasoning_for

    client, messages = _client(_message([_tool_use({"applicable_law": []})]))
    service_call = reasoning_for("korgan_claim_validation", "gpt-5.1")
    assert service_call == {"effort": "none"}

    await client.responses.create(
        model="gpt-5.1",
        instructions="",
        input="вопрос",
        text={"format": {"type": "json_schema", "name": "korgan_claim_validation", "schema": SCHEMA}},
        reasoning=service_call,
    )

    assert messages.request["output_config"]["effort"] == "low"


@_sync
async def test_unknown_openai_only_kwargs_do_not_break_the_call() -> None:
    """Вызывающий код передаёт поля OpenAI, которых у Anthropic нет."""
    client, messages = _client(_message([_tool_use({"applicable_law": []})]))

    await client.responses.create(
        model="gpt-5.1",
        instructions="",
        input="вопрос",
        text={"format": {"type": "json_schema", "name": "korgan_legal_research", "schema": SCHEMA}},
        prompt_cache_key="korgan:korgan_verified_legal_research:v5",
        include=["web_search_call.action.sources"],
        max_output_tokens=3600,
    )

    assert messages.request["max_tokens"] == 3600
    assert "prompt_cache_key" not in messages.request
    assert "include" not in messages.request


# --- перевод ответа --------------------------------------------------------

@_sync
async def test_urls_come_from_search_objects_by_both_readers() -> None:
    found = SimpleNamespace(type="web_search_result", url="https://adilet.zan.kz/rus/docs/K990000409_", title="ГК РК")
    cited = SimpleNamespace(
        type="text",
        text="Статья 715",
        citations=[SimpleNamespace(url="https://adilet.zan.kz/rus/docs/K1500000377", title="ГПК РК")],
    )
    client, _ = _client(_message([
        SimpleNamespace(type="web_search_tool_result", content=[found]),
        cited,
        _tool_use({"applicable_law": ["ГК РК 715"]}),
    ]))

    response = await client.responses.create(
        model="gpt-5.1",
        instructions="",
        input="вопрос",
        text={"format": {"type": "json_schema", "name": "korgan_legal_research", "schema": SCHEMA}},
        tools=[{"type": "web_search", "filters": {"allowed_domains": ["adilet.zan.kz"]}}],
    )

    by_dump = _actual_response_urls(response)
    by_attrs = OpenAILegalService._annotation_urls(response)
    assert "https://adilet.zan.kz/rus/docs/K990000409_" in by_dump
    assert "https://adilet.zan.kz/rus/docs/K1500000377" in by_dump
    assert set(by_attrs) == set(by_dump)


@_sync
async def test_text_urls_are_not_mistaken_for_sources() -> None:
    """URL, который модель напечатала, источником не является."""
    printed = SimpleNamespace(type="text", text="см. https://adilet.zan.kz/rus/docs/K990000409_", citations=[])
    client, _ = _client(_message([printed, _tool_use({"applicable_law": []})]))

    response = await client.responses.create(
        model="gpt-5.1",
        instructions="",
        input="вопрос",
        text={"format": {"type": "json_schema", "name": "korgan_legal_research", "schema": SCHEMA}},
    )

    assert _actual_response_urls(response) == []


@_sync
async def test_truncated_answer_is_not_reported_as_complete() -> None:
    client, _ = _client(_message([_tool_use({"applicable_law": []})], stop_reason="max_tokens"))

    response = await client.responses.create(
        model="gpt-5.1",
        instructions="",
        input="вопрос",
        text={"format": {"type": "json_schema", "name": "korgan_legal_research", "schema": SCHEMA}},
    )

    assert response.status == "incomplete"
    assert response.incomplete_details.reason == "max_output_tokens"


@_sync
async def test_answer_without_the_tool_call_is_incomplete() -> None:
    """Ответ обычным текстом вместо схемы — это отсутствие ответа."""
    client, _ = _client(_message([SimpleNamespace(type="text", text="Полагаю, что...", citations=[])], stop_reason="end_turn"))

    response = await client.responses.create(
        model="gpt-5.1",
        instructions="",
        input="вопрос",
        text={"format": {"type": "json_schema", "name": "korgan_legal_research", "schema": SCHEMA}},
    )

    assert response.status == "incomplete"
    assert response.output_text == ""


# --- видимость провайдера в проде ------------------------------------------

def test_health_reports_which_provider_actually_answers() -> None:
    """Смена провайдера обязана быть видна снаружи.

    Ключ в переменных окружения означает лишь намерение. Если SDK не поставлен,
    build_legal_client молча уходит на OpenAI — и без этого поля отличить
    «Anthropic отвечает» от «Anthropic не подключился» в проде было бы нечем.
    """
    from fastapi.testclient import TestClient

    from korgan.miniapp_api_recovery_cors import app

    with TestClient(app) as client:
        health = client.get("/health").json()

    assert health["ai_provider"] in {"anthropic", "openai"}


# --- откат на запасного ----------------------------------------------------

class _Failing:
    async def create(self, **kwargs: object) -> object:
        raise RuntimeError("429 rate limit")


class _Working:
    def __init__(self) -> None:
        self.calls = 0

    async def create(self, **kwargs: object) -> object:
        self.calls += 1
        return SimpleNamespace(output_text="{}", called_with=kwargs)


@_sync
async def test_provider_failure_falls_back_to_openai() -> None:
    working = _Working()
    client = FallbackClient(
        SimpleNamespace(responses=_Failing()),
        SimpleNamespace(responses=working),
        primary_name="anthropic",
        secondary_name="openai",
    )

    result = await client.responses.create(model="gpt-5.1", input="вопрос")

    assert working.calls == 1
    assert result.called_with["model"] == "gpt-5.1"


@_sync
async def test_incomplete_answer_does_not_trigger_fallback() -> None:
    """Отказ отвечать без источников — это результат, а не сбой провайдера.

    Повтор у второго провайдера превратил бы сознательный fail-closed в ещё
    одну попытку получить ответ любой ценой.
    """
    primary = _Working()
    secondary = _Working()
    incomplete = SimpleNamespace(output_text="", status="incomplete")

    async def create(**kwargs: object) -> object:
        primary.calls += 1
        return incomplete

    client = FallbackClient(
        SimpleNamespace(responses=SimpleNamespace(create=create)),
        SimpleNamespace(responses=secondary),
        primary_name="anthropic",
        secondary_name="openai",
    )

    result = await client.responses.create(model="gpt-5.1", input="вопрос")

    assert result is incomplete
    assert secondary.calls == 0
