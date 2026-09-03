import asyncio
import subprocess
import sys
import textwrap

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
    service = ClaimServiceMux(stable, object(), claim_factory=lambda settings: claim)

    research = asyncio.run(service.research_case("ctx", language="kk"))
    draft = asyncio.run(service.draft_claim("ctx", "r", language="ru"))

    assert research == ("claim-research", "ctx", "kk")
    assert draft == ("claim-draft", "ctx", "r", "ru")
    assert service.other_api == "stable-only"
    assert service.settings is stable.settings


def test_claim_service_is_lazy_and_reused():
    stable = _Stable()
    claim = _Claim()
    builds = []

    def factory(settings):
        builds.append(settings)
        return claim

    settings = object()
    service = ClaimServiceMux(stable, settings, claim_factory=factory)

    assert builds == []
    asyncio.run(service.research_case("first"))
    asyncio.run(service.draft_claim("second", "research"))
    assert builds == [settings]


def test_strict_runtime_wraps_stable_service_with_claim_mux_in_subprocess():
    script = textwrap.dedent(
        r'''
        import asyncio
        import os
        from types import SimpleNamespace
        from korgan import bot as base_bot
        from korgan import strict_bot
        from korgan.claim_service_mux import ClaimServiceMux

        # This regression deliberately exercises the active worker runtime. The
        # production Railway worker can be kill-switched independently, so do
        # not inherit that deployment flag into this subprocess contract test.
        os.environ.pop("KORGAN_TELEGRAM_AGENT_DISABLED", None)

        settings = SimpleNamespace(
            telegram_bot_token="test-token",
            payments_enabled=False,
            consultation_limit_enabled=False,
        )
        strict_bot.get_settings = lambda: settings
        strict_bot.apply_token_budget_guard = lambda current: None

        stable = SimpleNamespace(settings=settings, stable_marker=True)
        strict_bot.PretrialResponseProductionService = lambda current: stable
        strict_bot.ClaimPipelineV2Adapter = lambda inner: inner
        strict_bot.main_menu = lambda: object()

        class MiddlewareTarget:
            def outer_middleware(self, middleware):
                return None

        class FakeDispatcher:
            def __init__(self, *, storage):
                self.message = MiddlewareTarget()
                self.callback_query = MiddlewareTarget()
            def include_router(self, router):
                return None
            async def start_polling(self, bot):
                return None

        class FakeSession:
            async def close(self):
                return None

        class FakeBot:
            def __init__(self):
                self.session = FakeSession()

        async def noop(*args, **kwargs):
            return None

        strict_bot.Dispatcher = FakeDispatcher
        strict_bot.MemoryStorage = lambda: object()
        strict_bot.LanguageContextMiddleware = lambda: object()
        strict_bot.ConsentMiddleware = lambda: object()
        strict_bot.LocalizedClientSafeBot = lambda token: FakeBot()
        strict_bot.start_corpus_refresh_task = lambda: None
        strict_bot.claim_pipeline_v2_mode = lambda: "off"
        strict_bot.configure_telegram_menu = noop
        strict_bot.init_consultation_store = noop
        strict_bot.close_consultation_store = noop

        asyncio.run(strict_bot.main())
        assert isinstance(base_bot.service, ClaimServiceMux)
        assert base_bot.service.stable is stable
        assert base_bot.service._claim is None
        '''
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr