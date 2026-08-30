from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

from korgan.kaspi_ofd import KaspiOFDVerificationError

_T = TypeVar("_T")
_TRANSIENT_HTTP_CODES = {429, 500, 502, 503, 504}
_DEFAULT_DELAYS = (0.0, 0.35, 0.9)


def is_transient_ofd_error(exc: BaseException) -> bool:
    """Return True only for failures that can reasonably succeed on retry."""
    text = str(exc or "").casefold()
    if "не удалось получить фискальный чек" in text:
        return True
    if "вернул пустой чек" in text:
        return True
    for code in _TRANSIENT_HTTP_CODES:
        if f"http {code}" in text:
            return True
    return False


async def retry_kaspi_ofd(
    operation: Callable[[], Awaitable[_T]],
    *,
    delays: tuple[float, ...] = _DEFAULT_DELAYS,
) -> _T:
    """Retry only transient OFD/network errors; never retry a bad receipt."""
    if not delays:
        delays = (0.0,)
    last_error: KaspiOFDVerificationError | None = None
    for attempt, delay in enumerate(delays):
        if attempt and delay > 0:
            await asyncio.sleep(delay)
        try:
            return await operation()
        except KaspiOFDVerificationError as exc:
            if not is_transient_ofd_error(exc):
                raise
            last_error = exc
    assert last_error is not None
    raise last_error


def install_ofd_retry(module) -> None:  # noqa: ANN001
    """Install one process-local retry wrapper on miniapp_api_ofd fetches."""
    current = module.fetch_kaspi_ofd_receipt
    if getattr(current, "__korgan_ofd_retry__", False):
        return

    async def resilient_fetch(url: str, *args, **kwargs):  # noqa: ANN002, ANN003
        return await retry_kaspi_ofd(lambda: current(url, *args, **kwargs))

    setattr(resilient_fetch, "__korgan_ofd_retry__", True)
    module.fetch_kaspi_ofd_receipt = resilient_fetch
