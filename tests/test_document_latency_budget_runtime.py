from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException


def test_document_generation_timeout_is_clamped_to_product_window(monkeypatch: pytest.MonkeyPatch) -> None:
    import korgan.document_latency_budget_runtime as runtime

    monkeypatch.setenv(runtime._TIMEOUT_ENV, "999")
    assert runtime.document_generation_timeout_seconds() == runtime._MAX_TIMEOUT_SECONDS

    monkeypatch.setenv(runtime._TIMEOUT_ENV, "1")
    assert runtime.document_generation_timeout_seconds() == runtime._MIN_TIMEOUT_SECONDS

    monkeypatch.setenv(runtime._TIMEOUT_ENV, "not-a-number")
    assert runtime.document_generation_timeout_seconds() == runtime._DEFAULT_TIMEOUT_SECONDS


def test_slow_document_pipeline_fails_closed_before_partial_word(monkeypatch: pytest.MonkeyPatch) -> None:
    import korgan.document_latency_budget_runtime as runtime

    async def slow_generate(document_type: str, context: str, language: str):
        await asyncio.sleep(0.2)
        raise AssertionError("timeout should cancel the underlying generation")

    monkeypatch.setattr(runtime, "_ORIGINAL_GENERATE", slow_generate)
    monkeypatch.setattr(runtime, "document_generation_timeout_seconds", lambda: 0.01)

    async def scenario() -> None:
        with pytest.raises(HTTPException) as raised:
            await runtime._bounded_generate("claim", "case", "ru")
        assert raised.value.status_code == 504
        assert "не уложился" in str(raised.value.detail)
        assert "Непроверенный или незавершённый Word не выдан" in str(raised.value.detail)

    asyncio.run(scenario())


def test_fast_document_pipeline_returns_unchanged_result(monkeypatch: pytest.MonkeyPatch) -> None:
    import korgan.document_latency_budget_runtime as runtime

    expected = (object(), b"docx", "claim.docx", {"filing_ready": True})

    async def fast_generate(document_type: str, context: str, language: str):
        return expected

    monkeypatch.setattr(runtime, "_ORIGINAL_GENERATE", fast_generate)
    monkeypatch.setattr(runtime, "document_generation_timeout_seconds", lambda: 0.5)

    result = asyncio.run(runtime._bounded_generate("claim", "case", "ru"))
    assert result is expected
