from __future__ import annotations

"""Request-local progress reporting for document generation.

The generation job owns the user-visible status. The legal pipeline reports only
actual stage boundaries; it never invents time-based percentages. A ContextVar
keeps concurrent users isolated and lets nested runtime wrappers (live article
verification, DOCX rendering, etc.) report progress without global mutable state.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Callable, Iterator

ProgressCallback = Callable[[str, int], None]
_CURRENT: ContextVar[ProgressCallback | None] = ContextVar(
    "korgan_generation_progress_callback",
    default=None,
)


def report(stage: str, progress: int) -> None:
    callback = _CURRENT.get()
    if callback is None:
        return
    callback(str(stage or "queued"), max(0, min(int(progress), 100)))


@contextmanager
def bind(callback: ProgressCallback) -> Iterator[None]:
    token = _CURRENT.set(callback)
    try:
        yield
    finally:
        _CURRENT.reset(token)
