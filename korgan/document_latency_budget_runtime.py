from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

from fastapi import HTTPException

from korgan import miniapp_api_v2 as core

LOGGER = logging.getLogger(__name__)

_TIMEOUT_ENV = "KORGAN_DOCUMENT_GENERATION_TIMEOUT_SECONDS"
# The previous 110-second product target became a hard failure mode: valid
# documents were cancelled exactly while legal research was still running. The
# UI now reports real stages, so the server budget is a safety ceiling rather
# than a customer-facing promise.
_DEFAULT_TIMEOUT_SECONDS = 360.0
_MIN_TIMEOUT_SECONDS = 240.0
_MAX_TIMEOUT_SECONDS = 600.0
_INSTALLED = False
_ORIGINAL_GENERATE = core._generate


def document_generation_timeout_seconds() -> float:
    raw = str(os.getenv(_TIMEOUT_ENV, "") or "").strip()
    try:
        configured = float(raw) if raw else _DEFAULT_TIMEOUT_SECONDS
    except ValueError:
        configured = _DEFAULT_TIMEOUT_SECONDS
    # Existing Railway values such as 110 seconds are deliberately lifted to
    # the new safety floor so an old variable cannot keep killing generation.
    return min(_MAX_TIMEOUT_SECONDS, max(_MIN_TIMEOUT_SECONDS, configured))


async def _bounded_generate(
    document_type: str,
    context: str,
    language: str,
) -> tuple[Any, bytes, str, dict[str, Any]]:
    timeout = document_generation_timeout_seconds()
    started = time.perf_counter()
    status = "ok"
    try:
        async with asyncio.timeout(timeout):
            return await _ORIGINAL_GENERATE(document_type, context, language)
    except TimeoutError as exc:
        status = "timeout"
        raise HTTPException(
            status_code=504,
            detail=(
                "KORGAN не завершил подготовку документа в пределах технического лимита. "
                "Непроверенный или незавершённый Word не выдан. Материалы дела сохранены — "
                "подготовку можно повторить без потери данных."
            ),
        ) from exc
    except Exception:
        status = "error"
        raise
    finally:
        LOGGER.info(
            "DOCUMENT_GENERATION_LATENCY document_type=%s seconds=%.2f budget=%.0f status=%s",
            document_type,
            time.perf_counter() - started,
            timeout,
            status,
        )


def install_document_latency_budget_runtime() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    core._generate = _bounded_generate  # type: ignore[assignment]
    _INSTALLED = True
    LOGGER.info(
        "Installed document generation safety ceiling seconds=%.0f",
        document_generation_timeout_seconds(),
    )


install_document_latency_budget_runtime()
