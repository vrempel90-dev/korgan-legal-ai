from __future__ import annotations

import asyncio
from types import SimpleNamespace


def test_response_usage_snapshot_supports_sdk_objects_and_missing_usage():
    from korgan.openai_usage_observability import response_usage_snapshot

    response = SimpleNamespace(
        usage=SimpleNamespace(
            input_tokens=12_000,
            input_tokens_details=SimpleNamespace(cached_tokens=9_000),
            output_tokens=1_500,
            output_tokens_details=SimpleNamespace(reasoning_tokens=300),
            total_tokens=13_500,
        )
    )
    assert response_usage_snapshot(response) == {
        "input_tokens": 12_000,
        "cached_input_tokens": 9_000,
        "output_tokens": 1_500,
        "reasoning_tokens": 300,
        "total_tokens": 13_500,
    }
    assert response_usage_snapshot(SimpleNamespace()) == {
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_tokens": 0,
        "total_tokens": 0,
    }


def test_usage_observer_preserves_arguments_and_return_value(caplog):
    from korgan import openai_usage_observability as observer
    from korgan import robust_production_legal as robust

    cls = robust.ProductionOpenAILegalService
    original = cls._structured_response
    observer_installed = observer._INSTALLED
    seen: dict[str, object] = {}
    response = SimpleNamespace(
        usage={
            "input_tokens": 100,
            "input_tokens_details": {"cached_tokens": 80},
            "output_tokens": 25,
            "output_tokens_details": {"reasoning_tokens": 0},
            "total_tokens": 125,
        }
    )
    payload = {"ok": True}

    async def fake_structured_response(
        self,
        *,
        model,
        instructions,
        content,
        schema_name,
        schema,
        tools=None,
    ):
        seen.update(
            model=model,
            instructions=instructions,
            content=content,
            schema_name=schema_name,
            schema=schema,
            tools=tools,
        )
        return payload, response

    try:
        caplog.set_level("INFO", logger="korgan.openai_usage_observability")
        cls._structured_response = fake_structured_response
        observer._INSTALLED = False
        observer.install_openai_usage_observability()
        service = object.__new__(cls)
        result = asyncio.run(
            service._structured_response(
                model="gpt-5.1",
                instructions="same instructions",
                content="same content",
                schema_name="test_schema",
                schema={"type": "object"},
                tools=[{"type": "web_search"}],
            )
        )
        assert result == (payload, response)
        assert seen == {
            "model": "gpt-5.1",
            "instructions": "same instructions",
            "content": "same content",
            "schema_name": "test_schema",
            "schema": {"type": "object"},
            "tools": [{"type": "web_search"}],
        }
        assert "OPENAI_USAGE schema=test_schema model=gpt-5.1" in caplog.text
        assert "input_tokens=100" in caplog.text
        assert "cached_input_tokens=80" in caplog.text
        assert "output_tokens=25" in caplog.text
    finally:
        cls._structured_response = original
        observer._INSTALLED = observer_installed
