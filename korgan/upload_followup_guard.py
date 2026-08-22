from __future__ import annotations

import logging
from typing import Any

LOGGER = logging.getLogger(__name__)

_OLD_FOLLOWUP = (
    "Если всё верно, можно добавить ещё документы или попросить подготовить иск — "
    "он придёт файлом Word (.docx)."
)
_NEW_FOLLOWUP = (
    "Если всё верно, можно добавить ещё документы или продолжить подготовку "
    "выбранного документа."
)
_INSTALLED = False
_ORIGINAL_ANALYZE_UPLOAD: Any = None


class _UploadMessageProxy:
    """Change only the legacy claim-specific post-upload sentence."""

    def __init__(self, original: Any) -> None:
        self._original = original

    def __getattr__(self, name: str) -> Any:
        return getattr(self._original, name)

    async def answer(self, text: Any, *args: Any, **kwargs: Any) -> Any:
        value = str(text)
        if _OLD_FOLLOWUP in value:
            value = value.replace(_OLD_FOLLOWUP, _NEW_FOLLOWUP)
        return await self._original.answer(value, *args, **kwargs)


def install_upload_followup_guard() -> None:
    """Keep upload analysis neutral for claim/response/pretrial/contract flows.

    The legacy analyzer predates the document-category router and always tells the
    client to request an иск after parsing an upload. That is misleading when the
    selected document is, for example, an отзыв на иск. The extraction and state
    logic remain untouched; only the exact legacy sentence is replaced.
    """
    global _INSTALLED, _ORIGINAL_ANALYZE_UPLOAD
    if _INSTALLED:
        return

    from korgan import bot as base_bot

    original = base_bot._analyze_upload
    _ORIGINAL_ANALYZE_UPLOAD = original

    async def guarded_analyze_upload(
        message: Any,
        state: Any,
        data: bytes,
        filename: str,
        mime_type: str | None,
    ) -> None:
        await original(_UploadMessageProxy(message), state, data, filename, mime_type)

    base_bot._analyze_upload = guarded_analyze_upload
    _INSTALLED = True
    LOGGER.info("KORGAN document-neutral upload follow-up guard installed")
