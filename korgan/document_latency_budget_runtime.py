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
_DEFAULT_TIMEOUT_SECONDS = 110.0
# The product promise is a one-to-two minute preparation window. Keep a few
# seconds outside the legal pipeline for state persistence and the final status
# response; an operator cannot accidentally configure a five-minute request.
_MAX_TIMEOUT_SECONDS = 115.0
_MIN_TIMEOUT_SECONDS = 30.0
_INSTALLED = False
_ORIGINAL_GENERATE = core._generate


def document_generation_timeout_seconds() -> float:
    raw = str(os.getenv(_TIMEOUT_ENV, "") or "").strip()
    try:
        configured = float(raw) if raw else _DEFAULT_TIMEOUT_SECONDS
    except ValueError:
        configured = _DEFAULT_TIMEOUT_SECONDS
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
                "KORGAN остановил подготовку, потому что юридический конвейер не уложился "
                f"в {int(timeout)} секунд. Непроверенный или незавершённый Word не выдан. "
                "Материалы дела сохранены; повторите подготовку документа."
            ),
        ) from exc
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
        "Installed bounded document generation latency budget seconds=%.0f",
        document_generation_timeout_seconds(),
    )


install_document_latency_budget_runtime()
