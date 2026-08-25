"""Read-only OpenAI token/latency observability for KORGAN production calls.

The observer never changes model selection, prompts, tools, token limits,
reasoning settings, response schemas or returned values.  It only reads usage
metadata from an already completed Responses API call and emits aggregate token
counts suitable for cost analysis.  No user text or document content is logged.
"""

from __future__ import annotations

import logging
import time
from typing import Any

LOGGER = logging.getLogger(__name__)
_INSTALLED = False


def _field(value: Any, name: str, default: Any = None) -> Any:
    """Read one SDK usage field from either an object or mapping."""
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _token_count(value: Any) -> int:
    """Return a non-negative integer token count without raising on SDK drift."""
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def response_usage_snapshot(response: Any) -> dict[str, int]:
    """Extract non-sensitive token counters from an OpenAI Responses object."""
    usage = _field(response, "usage")
    if usage is None:
        return {
            "input_tokens": 0,
            "cached_input_tokens": 0,
            "output_tokens": 0,
            "reasoning_tokens": 0,
            "total_tokens": 0,
        }

    input_details = _field(usage, "input_tokens_details") or {}
    output_details = _field(usage, "output_tokens_details") or {}
    input_tokens = _token_count(_field(usage, "input_tokens"))
    output_tokens = _token_count(_field(usage, "output_tokens"))
    total_tokens = _token_count(_field(usage, "total_tokens"))
    if total_tokens <= 0:
        total_tokens = input_tokens + output_tokens

    return {
        "input_tokens": input_tokens,
        "cached_input_tokens": _token_count(_field(input_details, "cached_tokens")),
        "output_tokens": output_tokens,
        "reasoning_tokens": _token_count(_field(output_details, "reasoning_tokens")),
        "total_tokens": total_tokens,
    }


def install_openai_usage_observability() -> None:
    """Log usage after each completed structured call without changing behavior."""
    global _INSTALLED
    if _INSTALLED:
        return

    from korgan import robust_production_legal as robust

    cls = robust.ProductionOpenAILegalService
    current = cls._structured_response
    if getattr(current, "_korgan_usage_observer", False):
        _INSTALLED = True
        return

    async def observed_structured_response(
        self: Any,
        *,
        model: str,
        instructions: str,
        content: list[dict[str, Any]] | str,
        schema_name: str,
        schema: dict[str, Any],
        tools: list[dict[str, Any]] | None = None,
    ):
        started = time.perf_counter()
        result = await current(
            self,
            model=model,
            instructions=instructions,
            content=content,
            schema_name=schema_name,
            schema=schema,
            tools=tools,
        )
        elapsed = time.perf_counter() - started
        payload, response = result
        usage = response_usage_snapshot(response)
        LOGGER.info(
            "OPENAI_USAGE schema=%s model=%s input_tokens=%d cached_input_tokens=%d output_tokens=%d reasoning_tokens=%d total_tokens=%d wall_seconds=%.2f",
            schema_name,
            model,
            usage["input_tokens"],
            usage["cached_input_tokens"],
            usage["output_tokens"],
            usage["reasoning_tokens"],
            usage["total_tokens"],
            elapsed,
        )
        return payload, response

    observed_structured_response._korgan_usage_observer = True  # type: ignore[attr-defined]
    cls._structured_response = observed_structured_response
    _INSTALLED = True
    LOGGER.info("Installed KORGAN read-only OpenAI usage observability")
