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
_OLD_FOLLOWUP_KK = (
    "Қосымша материал жіберуге немесе бірден талап қою арызын дайындауды сұрауға болады."
)
_PRETRIAL_RESPONSE_FOLLOWUP_KK = (
    "Қосымша материал жіберуге немесе сотқа дейінгі талапқа жауапты дайындауды "
    "жалғастыруға болады."
)
_INSTALLED = False
_ORIGINAL_ANALYZE_UPLOAD: Any = None
_ORIGINAL_ANALYZE_UPLOAD_KK: Any = None


class _UploadMessageProxy:
    """Replace one exact legacy post-upload sentence without touching extraction output."""

    def __init__(self, original: Any, old_followup: str = _OLD_FOLLOWUP, new_followup: str = _NEW_FOLLOWUP) -> None:
        self._original = original
        self._old_followup = old_followup
        self._new_followup = new_followup

    def __getattr__(self, name: str) -> Any:
        return getattr(self._original, name)

    async def answer(self, text: Any, *args: Any, **kwargs: Any) -> Any:
        value = str(text)
        if self._old_followup in value:
            value = value.replace(self._old_followup, self._new_followup)
        return await self._original.answer(value, *args, **kwargs)


def install_upload_followup_guard() -> None:
    """Prevent legacy claim CTAs from leaking into another selected document flow.

    The base analyzer predates the document-category router. The Kazakh UI also
    owns its own upload analyzer, so `pretrial_response` needs the same surgical
    CTA correction on that path. Extraction, saved state, and document generation
    remain untouched.
    """
    global _INSTALLED, _ORIGINAL_ANALYZE_UPLOAD, _ORIGINAL_ANALYZE_UPLOAD_KK
    if _INSTALLED:
        return

    from korgan import bot as base_bot
    from korgan import kazakh_ui

    original = base_bot._analyze_upload
    original_kk = kazakh_ui._analyze_upload_kk
    _ORIGINAL_ANALYZE_UPLOAD = original
    _ORIGINAL_ANALYZE_UPLOAD_KK = original_kk

    async def guarded_analyze_upload(
        message: Any,
        state: Any,
        data: bytes,
        filename: str,
        mime_type: str | None,
    ) -> None:
        await original(_UploadMessageProxy(message), state, data, filename, mime_type)

    async def guarded_analyze_upload_kk(
        message: Any,
        state: Any,
        data: bytes,
        filename: str,
        mime_type: str | None,
    ) -> None:
        state_data = await state.get_data()
        if state_data.get("request_kind") == "pretrial_response":
            message = _UploadMessageProxy(
                message,
                old_followup=_OLD_FOLLOWUP_KK,
                new_followup=_PRETRIAL_RESPONSE_FOLLOWUP_KK,
            )
        await original_kk(message, state, data, filename, mime_type)

    base_bot._analyze_upload = guarded_analyze_upload
    kazakh_ui._analyze_upload_kk = guarded_analyze_upload_kk
    _INSTALLED = True
    LOGGER.info("KORGAN document-neutral upload follow-up guard installed")
