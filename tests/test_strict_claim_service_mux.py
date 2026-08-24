import asyncio
from types import SimpleNamespace

import pytest

from korgan import bot as base_bot
from korgan import claim_service_mux
from korgan import strict_bot
from korgan.claim_pipeline_v2 import ClaimPipelineV2Adapter
from korgan.claim_service_mux import ClaimServiceMux


class _Stable:
    def __init__(self):
        self.settings = object()
        self.other_api = "stable-only"


class _Claim:
    async def research_case(self, case_context: str, language: str = "ru"):
        return ("claim-research", case_context, language)

    async def draft_claim(self, case_context: str, research, language: str = "ru"):
        return ("claim-draft", case_context, research, language)


def test_claim_service_mux_routes_only_claim_methods():
    stable = _Stable()
    claim = _Claim()
    service = ClaimServiceMux(stable, claim)

    research = asyncio.run(service.research_case("ctx", language="kk"))
    draft = asyncio.run(service.draft_claim("ctx", "r", language="ru"))

    assert research == ("claim-research", "ctx", "kk")
    assert draft == ("claim-draft", "ctx", "r", "ru")
    assert service.other_api == "stable-only"
    assert service.settings is stable.settings


def test_builder_wraps_mux_in_claim_pipeline(monkeypatch):
    stable = _Stable()
    claim = _Claim()

    monkeypatch.setattr(claim_service_mux, "PretrialResponseProductionService", lambda settings: stable)
    monkeypatch.setattr(claim_service_mux, "FinalizedProductionClaimService", lambda settings: claim)

    service = claim_service_mux.build_strict_legal_service(object())

    assert isinstance(service, ClaimPipelineV2Adapter)
    assert isinstance(service.inner, ClaimServiceMux)
    assert service.inner.stable is stable
    assert service.inner.claim is claim


def test_strict_bot_main_installs_built_service(monkeypatch):
    marker = object()
    settings = SimpleNamespace(
        telegram_bot_token="123:TEST",
        payments_enabled=False,
        consultation_limit_enabled=False,
    )

    monkeypatch.setattr(strict_bot, "get_settings", lambda: settings)
    monkeypatch.setattr(strict_bot, "apply_token_budget_guard", lambda current: None)
    monkeypatch.setattr(strict_bot, "build_strict_legal_service", lambda current: marker)
    monkeypatch.setattr(strict_bot, "init_consultation_store", lambda current: _noop())
    monkeypatch.setattr(strict_bot, "close_consultation_store", _noop)
    monkeypatch.setattr(strict_bot, "start_corpus_refresh_task", lambda: None)
    monkeypatch.setattr(strict_bot, "configure_telegram_menu", _noop_bot)
    monkeypatch.setattr(strict_bot, "LocalizedClientSafeBot", lambda token: _FakeBot())
    monkeypatch.setattr(strict_bot, "Dispatcher", _FakeDispatcher)
    monkeypatch.setattr(strict_bot, "LanguageContextMiddleware", lambda: object())
    monkeypatch.setattr(strict_bot, "ConsentMiddleware", lambda: object())

    asyncio.run(strict_bot.main())

    assert base_bot.service is marker


async def _noop(*args, **kwargs):
    return None


async def _noop_bot(*args, **kwargs):
    return None


class _FakeSession:
    async def close(self):
        return None


class _FakeBot:
    def __init__(self):
        self.session = _FakeSession()


class _FakeMiddleware:
    def outer_middleware(self, middleware):
        return None


class _FakeDispatcher:
    def __init__(self, *args, **kwargs):
        self.message = _FakeMiddleware()
        self.callback_query = _FakeMiddleware()

    def include_router(self, router):
        return None

    async def start_polling(self, bot):
        return None
