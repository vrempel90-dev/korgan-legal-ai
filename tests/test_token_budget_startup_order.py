from __future__ import annotations

import asyncio
from types import SimpleNamespace

from korgan import strict_bot


class _MiddlewareTarget:
    def outer_middleware(self, _middleware) -> None:
        return None


class _FakeDispatcher:
    def __init__(self, *, storage) -> None:
        self.storage = storage
        self.message = _MiddlewareTarget()
        self.callback_query = _MiddlewareTarget()

    def include_router(self, _router) -> None:
        return None

    async def start_polling(self, _bot) -> None:
        return None


class _FakeSession:
    async def close(self) -> None:
        return None


class _FakeBot:
    def __init__(self) -> None:
        self.session = _FakeSession()


def test_main_applies_budget_guard_before_legal_service_construction(monkeypatch) -> None:
    events: list[str] = []
    settings = SimpleNamespace(
        telegram_bot_token="test-token",
        payments_enabled=False,
        consultation_limit_enabled=False,
    )

    monkeypatch.setattr(strict_bot, "get_settings", lambda: settings)
    monkeypatch.setattr(
        strict_bot,
        "apply_token_budget_guard",
        lambda received: events.append("budget_guard"),
    )

    def stable_service(received):
        assert received is settings
        events.append("stable_service")
        return SimpleNamespace(settings=received)

    def pipeline_adapter(inner):
        assert inner.settings is settings
        events.append("pipeline_adapter")
        return inner

    monkeypatch.setattr(strict_bot, "PretrialResponseProductionService", stable_service)
    monkeypatch.setattr(strict_bot, "ClaimPipelineV2Adapter", pipeline_adapter)
    monkeypatch.setattr(strict_bot, "main_menu", lambda: object())
    monkeypatch.setattr(strict_bot, "Dispatcher", _FakeDispatcher)
    monkeypatch.setattr(strict_bot, "MemoryStorage", lambda: object())
    monkeypatch.setattr(strict_bot, "LanguageContextMiddleware", lambda: object())
    monkeypatch.setattr(strict_bot, "ConsentMiddleware", lambda: object())
    monkeypatch.setattr(strict_bot, "LocalizedClientSafeBot", lambda token: _FakeBot())
    monkeypatch.setattr(strict_bot, "start_corpus_refresh_task", lambda: None)
    monkeypatch.setattr(strict_bot, "claim_pipeline_v2_mode", lambda: "off")

    async def noop(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(strict_bot, "configure_telegram_menu", noop)
    monkeypatch.setattr(strict_bot, "init_consultation_store", noop)
    monkeypatch.setattr(strict_bot, "close_consultation_store", noop)

    asyncio.run(strict_bot.main())

    assert events[:3] == ["budget_guard", "stable_service", "pipeline_adapter"]
