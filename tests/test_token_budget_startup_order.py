from __future__ import annotations

import subprocess
import sys
import textwrap


def test_main_applies_budget_guard_before_legal_service_construction() -> None:
    """Run the real strict_bot.main integration check in an isolated interpreter.

    strict_bot intentionally installs production runtime hotfixes at import time.
    Importing it during pytest collection would mutate process-global modules and
    invalidate unrelated regression tests. A subprocess preserves the behavioral
    startup-order assertion requested by CodeRabbit without polluting the suite.
    """
    script = textwrap.dedent(
        r'''
        import asyncio
        from types import SimpleNamespace
        from korgan import strict_bot

        events = []
        settings = SimpleNamespace(
            telegram_bot_token="test-token",
            payments_enabled=False,
            consultation_limit_enabled=False,
        )

        strict_bot.get_settings = lambda: settings
        strict_bot.apply_token_budget_guard = lambda received: events.append("budget_guard")

        def stable_service(received):
            assert received is settings
            events.append("stable_service")
            return SimpleNamespace(settings=received)

        def pipeline_adapter(inner):
            assert inner.settings is settings
            events.append("pipeline_adapter")
            return inner

        class MiddlewareTarget:
            def outer_middleware(self, _middleware):
                return None

        class FakeDispatcher:
            def __init__(self, *, storage):
                self.storage = storage
                self.message = MiddlewareTarget()
                self.callback_query = MiddlewareTarget()
            def include_router(self, _router):
                return None
            async def start_polling(self, _bot):
                return None

        class FakeSession:
            async def close(self):
                return None

        class FakeBot:
            def __init__(self):
                self.session = FakeSession()

        async def noop(*_args, **_kwargs):
            return None

        strict_bot.PretrialResponseProductionService = stable_service
        strict_bot.ClaimPipelineV2Adapter = pipeline_adapter
        strict_bot.main_menu = lambda: object()
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
        assert events[:3] == ["budget_guard", "stable_service", "pipeline_adapter"], events
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
