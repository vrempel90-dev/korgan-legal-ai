from __future__ import annotations

import asyncio

from korgan import ai_provider
from korgan import legal_search_latency_guard as guard


def test_bounded_search_keeps_official_domains_and_caps_uses():
    tools = [{
        "type": "web_search",
        "filters": {"allowed_domains": ["adilet.zan.kz", "sud.gov.kz"]},
        "search_context_size": "high",
    }]
    translated = guard.bounded_search_tools(tools)
    assert len(translated) == 1
    assert translated[0]["allowed_domains"] == ["adilet.zan.kz", "sud.gov.kz"]
    assert translated[0]["max_uses"] == 3


def test_low_context_is_limited_to_two_search_uses():
    translated = guard.bounded_search_tools([{
        "type": "web_search",
        "filters": {"allowed_domains": ["adilet.zan.kz"]},
        "search_context_size": "low",
    }])
    assert translated[0]["max_uses"] == 2


def test_slow_primary_web_search_falls_back_without_waiting_for_full_request(monkeypatch):
    calls = {"primary": 0, "secondary": 0}

    class Primary:
        async def create(self, **_kwargs):
            calls["primary"] += 1
            await asyncio.sleep(0.2)
            return "primary"

    class Secondary:
        async def create(self, **_kwargs):
            calls["secondary"] += 1
            return "secondary"

    monkeypatch.setattr(guard, "primary_web_search_timeout_seconds", lambda: 0.01)
    client = ai_provider.FallbackResponses(
        Primary(),
        Secondary(),
        primary_name="anthropic",
        secondary_name="openai",
    )
    result = asyncio.run(client.create(tools=[{"type": "web_search"}]))
    assert result == "secondary"
    assert calls == {"primary": 1, "secondary": 1}


def test_fast_primary_web_search_stays_on_primary(monkeypatch):
    calls = {"primary": 0, "secondary": 0}

    class Primary:
        async def create(self, **_kwargs):
            calls["primary"] += 1
            return "primary"

    class Secondary:
        async def create(self, **_kwargs):
            calls["secondary"] += 1
            return "secondary"

    monkeypatch.setattr(guard, "primary_web_search_timeout_seconds", lambda: 0.05)
    client = ai_provider.FallbackResponses(
        Primary(),
        Secondary(),
        primary_name="anthropic",
        secondary_name="openai",
    )
    result = asyncio.run(client.create(tools=[{"type": "web_search"}]))
    assert result == "primary"
    assert calls == {"primary": 1, "secondary": 0}


def test_non_search_drafting_is_not_subject_to_web_timeout(monkeypatch):
    calls = {"primary": 0, "secondary": 0}

    class Primary:
        async def create(self, **_kwargs):
            calls["primary"] += 1
            await asyncio.sleep(0.02)
            return "draft"

    class Secondary:
        async def create(self, **_kwargs):
            calls["secondary"] += 1
            return "secondary"

    monkeypatch.setattr(guard, "primary_web_search_timeout_seconds", lambda: 0.001)
    client = ai_provider.FallbackResponses(
        Primary(),
        Secondary(),
        primary_name="anthropic",
        secondary_name="openai",
    )
    result = asyncio.run(client.create(tools=[]))
    assert result == "draft"
    assert calls == {"primary": 1, "secondary": 0}
