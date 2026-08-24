import asyncio

from korgan import production_runtime
from korgan.state_duty_final_hotfix import ProductionOpenAILegalService as FinalLegalService


def test_importing_production_runtime_does_not_mutate_bot_wiring(monkeypatch) -> None:
    sentinel = object()
    monkeypatch.setattr(production_runtime.bot_module, "OpenAILegalService", sentinel)

    # Import-time behavior is deliberately inert; the swap happens in main().
    assert production_runtime.bot_module.OpenAILegalService is sentinel


def test_production_runtime_wires_final_service_during_startup(monkeypatch) -> None:
    seen = {}
    original = production_runtime.bot_module.OpenAILegalService

    async def fake_bot_main() -> None:
        seen["service"] = production_runtime.bot_module.OpenAILegalService

    monkeypatch.setattr(production_runtime.bot_module, "main", fake_bot_main)
    try:
        asyncio.run(production_runtime.main())
    finally:
        production_runtime.bot_module.OpenAILegalService = original

    assert production_runtime.ProductionOpenAILegalService is FinalLegalService
    assert seen["service"] is FinalLegalService
