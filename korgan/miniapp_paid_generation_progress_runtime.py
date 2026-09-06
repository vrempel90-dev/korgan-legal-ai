from __future__ import annotations

"""Backend-driven progress for paid Mini App document generation.

The production paid worker already persists job status. This runtime only wires
real legal-pipeline boundaries into that existing status channel. It does not
add model calls, timers, extra legal passes or a second generation path.

Important invariants:
- progress is reported only when the backend crosses a real operation boundary;
- the existing ``_generate_payload`` remains the document implementation, so
  release policy, DOCX cleanup and every previously deployed guard stay intact;
- progress writes are serialized and monotonic even though synchronous pipeline
  callbacks need to reach an async database writer;
- progress failures never abort a paid document that can otherwise be produced.
"""

import asyncio
import logging
from types import MethodType
from typing import Any, Awaitable, Callable

from korgan import generation_progress
from korgan import live_article_release_runtime as live
from korgan import miniapp_api_v2 as core
from korgan import miniapp_generation_jobs as jobs

LOGGER = logging.getLogger(__name__)
_INSTALLED = False
_FLUSH_TIMEOUT_SECONDS = 1.0

_ORIGINAL_GENERATE_PAYLOAD = jobs._generate_payload


def _mark_wrapped(function: Any) -> Any:
    # Keep compatibility with the older admin/free real-progress runtime: when
    # it is enabled explicitly it sees the same marker and does not double-wrap
    # the legal pipeline.
    setattr(function, "_korgan_real_progress", True)
    setattr(function, "_korgan_paid_real_progress", True)
    return function


def _wrap_async_method(name: str, stage: str, start_progress: int, done_progress: int) -> None:
    original = getattr(core.service, name, None)
    if original is None or getattr(original, "_korgan_real_progress", False):
        return

    async def wrapped(_self: Any, *args: Any, **kwargs: Any) -> Any:
        generation_progress.report(stage, start_progress)
        result = await original(*args, **kwargs)
        generation_progress.report(stage, done_progress)
        return result

    _mark_wrapped(wrapped)
    setattr(core.service, name, MethodType(wrapped, core.service))


def _wrap_release_metadata() -> None:
    original = core._release_metadata
    if getattr(original, "_korgan_real_progress", False):
        return

    def wrapped(*args: Any, **kwargs: Any) -> dict[str, Any]:
        generation_progress.report("quality_control", 80)
        result = original(*args, **kwargs)
        generation_progress.report("quality_control", 88)
        return result

    _mark_wrapped(wrapped)
    core._release_metadata = wrapped  # type: ignore[assignment]


def _wrap_docx_builder(name: str) -> None:
    original = getattr(core, name, None)
    if original is None or getattr(original, "_korgan_real_progress", False):
        return

    def wrapped(*args: Any, **kwargs: Any) -> bytes:
        generation_progress.report("document_render", 90)
        result = original(*args, **kwargs)
        generation_progress.report("document_render", 94)
        return result

    _mark_wrapped(wrapped)
    setattr(core, name, wrapped)


def _wrap_live_verifier() -> None:
    original = live.verify_document_articles
    if getattr(original, "_korgan_real_progress", False):
        return

    async def wrapped(file_bytes: bytes) -> None:
        generation_progress.report("document_render", 95)
        await original(file_bytes)
        generation_progress.report("document_render", 98)

    _mark_wrapped(wrapped)
    live.verify_document_articles = wrapped  # type: ignore[assignment]


async def _generate_payload_with_real_progress(
    document_type: str,
    context: str,
    language: str,
    *,
    case_id: str,
    on_stage: Callable[[str, int], Awaitable[None]],
) -> dict[str, Any]:
    """Run the existing payload builder while serializing real stage events.

    ``generation_progress.report`` is synchronous by design, while the paid job
    persists state asynchronously. A tiny FIFO bridges the two without blocking
    the legal pipeline. The worker discards backwards/equal percentages, so the
    older coarse milestones still emitted by ``_generate_payload`` cannot move
    a newer real stage backwards.
    """

    queue: asyncio.Queue[tuple[str, int] | object] = asyncio.Queue()
    stop = object()
    max_progress = -1

    async def drain() -> None:
        nonlocal max_progress
        while True:
            item = await queue.get()
            try:
                if item is stop:
                    return
                stage, raw_value = item  # type: ignore[misc]
                value = max(0, min(int(raw_value), 100))
                if value <= max_progress:
                    continue
                # Advance the in-process monotonic watermark before touching the
                # database. A transient status-write failure must not let a later
                # stale milestone move the client backwards.
                max_progress = value
                try:
                    await on_stage(stage, value)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    LOGGER.warning(
                        "Mini App real progress update failed case_id=%s stage=%s progress=%s",
                        case_id,
                        stage,
                        value,
                        exc_info=True,
                    )
            finally:
                queue.task_done()

    worker = asyncio.create_task(drain(), name=f"korgan-real-progress-{case_id}")

    def report(stage: str, value: int) -> None:
        if not worker.done():
            queue.put_nowait((str(stage or "queued"), int(value)))

    async def queued_on_stage(stage: str, value: int) -> None:
        # Existing coarse milestones enter the same FIFO as the actual pipeline
        # events. This preserves backward compatibility while monotonic filtering
        # prevents them from overwriting a more advanced real stage.
        report(stage, value)

    try:
        with generation_progress.bind(report):
            return await _ORIGINAL_GENERATE_PAYLOAD(
                document_type,
                context,
                language,
                case_id=case_id,
                on_stage=queued_on_stage,
            )
    finally:
        try:
            await asyncio.wait_for(queue.join(), timeout=_FLUSH_TIMEOUT_SECONDS)
        except TimeoutError:
            LOGGER.warning("Mini App progress flush timed out case_id=%s", case_id)
        queue.put_nowait(stop)
        try:
            await asyncio.wait_for(worker, timeout=_FLUSH_TIMEOUT_SECONDS)
        except TimeoutError:
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)


def install_paid_generation_progress_runtime() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    # These are actual functions the production generator already executes.
    # Percentages are milestones at their real start/completion boundaries, not
    # estimates based on elapsed time.
    for method_name in (
        "research_case",
        "research_contract",
        "research_response_to_claim",
        "research_pretrial",
        "research_pretrial_response",
    ):
        _wrap_async_method(method_name, "legal_research", 20, 42)

    for method_name in (
        "draft_claim",
        "draft_contract",
        "draft_response_to_claim",
        "draft_pretrial",
        "draft_pretrial_response",
    ):
        _wrap_async_method(method_name, "legal_research", 45, 75)

    _wrap_release_metadata()
    for builder in (
        "build_claim_docx",
        "build_contract_docx",
        "build_response_to_claim_docx",
        "build_pretrial_docx",
        "build_pretrial_response_docx",
    ):
        _wrap_docx_builder(builder)
    _wrap_live_verifier()

    jobs._generate_payload = _generate_payload_with_real_progress  # type: ignore[assignment]
    _INSTALLED = True
    LOGGER.info("Installed paid Mini App backend-driven generation progress")


install_paid_generation_progress_runtime()
