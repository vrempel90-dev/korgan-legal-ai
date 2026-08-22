from __future__ import annotations

import asyncio
from types import SimpleNamespace

from korgan import claim_release_entrypoint


def test_deployed_worker_applies_budget_guard_before_bot_start(monkeypatch):
    events: list[str] = []
    settings = SimpleNamespace()

    monkeypatch.setattr(claim_release_entrypoint, "get_settings", lambda: settings)
    monkeypatch.setattr(
        claim_release_entrypoint,
        "apply_token_budget_guard",
        lambda received: events.append("budget_guard") if received is settings else None,
    )
    monkeypatch.setattr(
        claim_release_entrypoint.claim_quality_hotfix,
        "install_runtime_hotfix",
        lambda: events.append("claim_hotfix"),
    )

    async def fake_bot_main():
        events.append("bot_main")

    monkeypatch.setattr(claim_release_entrypoint.bot, "main", fake_bot_main)
    monkeypatch.setattr(asyncio, "run", lambda coroutine: (coroutine.close(), events.append("async_run")))

    claim_release_entrypoint.main()

    assert events[:3] == ["budget_guard", "claim_hotfix", "async_run"]
