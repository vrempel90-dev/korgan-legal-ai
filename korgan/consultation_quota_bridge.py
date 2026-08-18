from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from korgan.config import get_settings
from korgan.kazakh_ui import KazakhLegalText

LOGGER = logging.getLogger(__name__)
_INSTALLED = False
_ORIGINAL: Callable[..., Awaitable[bool]] | None = None


def install_consultation_quota_bridge() -> None:
    """Make the existing Kazakh legal-text handler yield to the quota router.

    The Kazakh router is intentionally registered before the generic base router.
    Without this bridge it would answer consultations before the persistent quota
    handler sees them.  We patch only the filter decision and only while the
    consultation limit feature flag is enabled; document/menu routing is untouched.
    """
    global _INSTALLED, _ORIGINAL
    if _INSTALLED:
        return

    original = KazakhLegalText.__call__
    _ORIGINAL = original

    async def quota_aware(self: KazakhLegalText, message: Any, state: Any) -> bool:
        if get_settings().consultation_limit_enabled:
            return False
        return await original(self, message, state)

    KazakhLegalText.__call__ = quota_aware  # type: ignore[method-assign]
    _INSTALLED = True
    LOGGER.info("KORGAN Kazakh consultation quota bridge installed")
