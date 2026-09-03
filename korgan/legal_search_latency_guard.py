from __future__ import annotations

"""Latency guard for source-bound legal web research.

Production traces showed single Anthropic web-search calls opening 60+ URLs and
consuming 80-107 seconds before drafting even began. This runtime keeps the
same official-source allowlist and the same verification gates, but limits the
number of server-side search tool uses and gives the existing OpenAI fallback a
chance before one slow primary request consumes the whole document budget.
"""

import asyncio
import logging
import os
from typing import Any

from korgan import ai_provider
from korgan import anthropic_responses

LOGGER = logging.getLogger(__name__)

_TIMEOUT_ENV = "KORGAN_PRIMARY_WEB_SEARCH_TIMEOUT_SECONDS"
_DEFAULT_TIMEOUT_SECONDS = 30.0
_MIN_TIMEOUT_SECONDS = 10.0
_MAX_TIMEOUT_SECONDS = 45.0

_SEARCH_USE_CAP = {
    "low": 2,
    "medium": 3,
    "high": 3,
}

_INSTALLED = False
_ORIGINAL_SEARCH_TOOLS = anthropic_responses._search_tools
_ORIGINAL_FALLBACK_CREATE = ai_provider.FallbackResponses.create


def primary_web_search_timeout_seconds() -> float:
    raw = str(os.getenv(_TIMEOUT_ENV, "") or "").strip()
    try:
        configured = float(raw) if raw else _DEFAULT_TIMEOUT_SECONDS
    except ValueError:
        configured = _DEFAULT_TIMEOUT_SECONDS
    return min(_MAX_TIMEOUT_SECONDS, max(_MIN_TIMEOUT_SECONDS, configured))


def _context_size(tool: dict[str, Any]) -> str:
    value = str(tool.get("search_context_size") or "medium").strip().lower()
    return value if value in _SEARCH_USE_CAP else "medium"


def bounded_search_tools(tools: Any) -> list[dict[str, Any]]:
    """Translate Anthropic search tools and cap server-side search iterations."""
    translated = _ORIGINAL_SEARCH_TOOLS(tools)
    source_tools = [
        tool for tool in (tools or [])
        if isinstance(tool, dict) and str(tool.get("type", "")).startswith("web_search")
    ]
    for index, tool in enumerate(translated):
        source = source_tools[index] if index < len(source_tools) else {}
        tool["max_uses"] = _SEARCH_USE_CAP[_context_size(source)]
    return translated


def _has_web_search(kwargs: dict[str, Any]) -> bool:
    return any(
        isinstance(tool, dict) and str(tool.get("type", "")).startswith("web_search")
        for tool in (kwargs.get("tools") or [])
    )


async def latency_aware_fallback_create(self: Any, **kwargs: Any) -> Any:
    """Time-box only web research; drafting keeps the normal provider path."""
    if not _has_web_search(kwargs):
        return await _ORIGINAL_FALLBACK_CREATE(self, **kwargs)

    timeout = primary_web_search_timeout_seconds()
    try:
        return await asyncio.wait_for(self._primary.create(**kwargs), timeout=timeout)
    except TimeoutError:
        LOGGER.warning(
            "KORGAN primary legal web search exceeded %.0fs — using %s fallback",
            timeout,
            self._secondary_name,
        )
    except Exception as error:  # noqa: BLE001 - preserve existing provider failover semantics
        LOGGER.warning(
            "KORGAN AI provider %s failed during legal web search (%s: %s) — retrying via %s",
            self._primary_name,
            type(error).__name__,
            error,
            self._secondary_name,
        )
    return await self._secondary.create(**kwargs)


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    anthropic_responses._search_tools = bounded_search_tools
    ai_provider.FallbackResponses.create = latency_aware_fallback_create
    _INSTALLED = True
    LOGGER.info(
        "Installed legal search latency guard primary_timeout=%.0fs caps=%s",
        primary_web_search_timeout_seconds(),
        _SEARCH_USE_CAP,
    )


install()
