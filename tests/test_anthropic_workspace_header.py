from __future__ import annotations

from types import SimpleNamespace

import pytest

import korgan.ai_provider as provider


class _FakeAsyncAnthropic:
    calls: list[dict[str, object]] = []

    def __init__(self, **kwargs: object) -> None:
        type(self).calls.append(kwargs)
        self.messages = SimpleNamespace()


def test_workspace_id_is_forwarded_as_default_header(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeAsyncAnthropic.calls.clear()
    monkeypatch.setenv("ANTHROPIC_WORKSPACE_ID", "  wrkspc_test123  ")

    client = provider._build_anthropic_sdk_client(
        "sk-ant-test",
        client_type=_FakeAsyncAnthropic,
    )

    assert isinstance(client, _FakeAsyncAnthropic)
    assert _FakeAsyncAnthropic.calls == [
        {
            "api_key": "sk-ant-test",
            "default_headers": {"anthropic-workspace-id": "wrkspc_test123"},
        }
    ]


def test_missing_workspace_id_preserves_existing_client_behavior(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeAsyncAnthropic.calls.clear()
    monkeypatch.delenv("ANTHROPIC_WORKSPACE_ID", raising=False)

    provider._build_anthropic_sdk_client(
        "sk-ant-test",
        client_type=_FakeAsyncAnthropic,
    )

    assert _FakeAsyncAnthropic.calls == [{"api_key": "sk-ant-test"}]


def test_blank_workspace_id_is_not_sent(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeAsyncAnthropic.calls.clear()
    monkeypatch.setenv("ANTHROPIC_WORKSPACE_ID", "   ")

    provider._build_anthropic_sdk_client(
        "sk-ant-test",
        client_type=_FakeAsyncAnthropic,
    )

    assert _FakeAsyncAnthropic.calls == [{"api_key": "sk-ant-test"}]
