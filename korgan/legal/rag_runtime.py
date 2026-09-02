"""Runtime wiring for KORGAN legal retrieval corpora."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from korgan.asgi_lifespan import add_lifespan
from korgan.legal.corpus_refresh import corpus_refresh_loop
from korgan.legal.upstream_rag import start_upstream_rag_task, upstream_rag_status

LOGGER = logging.getLogger(__name__)
_FALSEY = {"0", "false", "no", "off"}
_RUNTIME_ATTR = "_korgan_legal_rag_runtime_installed"


def official_autoload_enabled() -> bool:
    """Refresh the authoritative official snapshot by default unless explicitly disabled."""
    return os.getenv("KORGAN_CORPUS_AUTOLOAD", "1").strip().lower() not in _FALSEY


def start_official_corpus_task() -> asyncio.Task[None] | None:
    if not official_autoload_enabled():
        LOGGER.info("KORGAN official corpus autoload disabled")
        return None
    LOGGER.info("KORGAN official corpus autoload enabled")
    return asyncio.create_task(corpus_refresh_loop(), name="korgan-corpus-refresh")


def start_legal_rag_tasks() -> list[asyncio.Task[None]]:
    tasks: list[asyncio.Task[None]] = []
    official = start_official_corpus_task()
    if official is not None:
        tasks.append(official)
    upstream = start_upstream_rag_task()
    if upstream is not None:
        tasks.append(upstream)
    return tasks


async def stop_legal_rag_tasks(tasks: list[asyncio.Task[None]]) -> None:
    for task in tasks:
        if not task.done():
            task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


def install_rag_lifespan(app: Any) -> None:
    """Attach official refresh + broad upstream KZ bootstrap to an ASGI app once."""
    if getattr(app, _RUNTIME_ATTR, False):
        return
    tasks: list[asyncio.Task[None]] = []

    async def _startup() -> None:
        tasks.extend(start_legal_rag_tasks())
        state = upstream_rag_status()
        LOGGER.info(
            "KORGAN_RAG_START official_autoload=%s upstream_ready=%s upstream_rows=%d",
            official_autoload_enabled(),
            state.ready,
            state.rows,
        )

    async def _shutdown() -> None:
        await stop_legal_rag_tasks(tasks)
        tasks.clear()

    add_lifespan(app, startup=_startup, shutdown=_shutdown)
    setattr(app, _RUNTIME_ATTR, True)
