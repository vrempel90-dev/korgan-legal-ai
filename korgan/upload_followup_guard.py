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


def _same_request(data: dict[str, Any], request_id: str, request_kind: str) -> bool:
    return (
        str(data.get("request_id") or "") == request_id
        and str(data.get("request_kind") or "") == request_kind
    )


def install_upload_followup_guard() -> None:
    """Prevent legacy claim CTAs from leaking into another selected document flow.

    The base analyzer predates the document-category router. The Kazakh UI also
    owns its own upload analyzer. Its replacement preserves Kazakh client text,
    applies the same request-id isolation as the production base upload path, and
    uses the same request-kind CTA mapping for every supported document type.
    """
    global _INSTALLED, _ORIGINAL_ANALYZE_UPLOAD, _ORIGINAL_ANALYZE_UPLOAD_KK
    if _INSTALLED:
        return

    from korgan import bot as base_bot
    from korgan import kazakh_ui
    from korgan.i18n import KK, tr
    from korgan.request_race_guard import _upload_followup
    from korgan.request_scope import document_request_lock
    from korgan.ui import main_menu

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
        service = base_bot.service
        if service is None:
            return

        before = await state.get_data()
        request_id = str(before.get("request_id") or "")
        request_kind = str(before.get("request_kind") or "")

        await message.bot.send_chat_action(message.chat.id, "typing")
        try:
            extracted = await service.extract_document(data, filename, mime_type)
        except ValueError as exc:
            LOGGER.info("Kazakh upload rejected filename=%s error=%s", filename, exc)
            async with document_request_lock(state):
                latest = await state.get_data()
                if not _same_request(latest, request_id, request_kind):
                    LOGGER.info(
                        "STALE_UPLOAD_SUPPRESSED request_id=%s kind=%s file=%s",
                        request_id,
                        request_kind,
                        filename,
                    )
                    return
                await message.answer(
                    "PDF, DOCX, TXT, JPG, JPEG, PNG және WEBP форматтары қолдау табады.",
                    reply_markup=main_menu(KK),
                )
            return
        except Exception:
            LOGGER.exception("Kazakh document analysis failed")
            async with document_request_lock(state):
                latest = await state.get_data()
                if not _same_request(latest, request_id, request_kind):
                    LOGGER.info(
                        "STALE_UPLOAD_SUPPRESSED request_id=%s kind=%s file=%s",
                        request_id,
                        request_kind,
                        filename,
                    )
                    return
                await message.answer(tr(KK, "upload_error"), reply_markup=main_menu(KK))
            return

        async with document_request_lock(state):
            latest = await state.get_data()
            if not _same_request(latest, request_id, request_kind):
                LOGGER.info(
                    "STALE_UPLOAD_SUPPRESSED request_id=%s kind=%s file=%s",
                    request_id,
                    request_kind,
                    filename,
                )
                return
            count = await base_bot._save_document(state, extracted)
            preview = extracted.as_context()

        async with document_request_lock(state):
            latest = await state.get_data()
            if not _same_request(latest, request_id, request_kind):
                LOGGER.info(
                    "STALE_UPLOAD_SUPPRESSED request_id=%s kind=%s file=%s",
                    request_id,
                    request_kind,
                    filename,
                )
                return
            text = (
                f"✅ Материал талданып, іске қосылды ({count}).\n\n{preview[:3200]}\n\n"
                + _upload_followup(request_kind, KK)
            )
            await message.answer(text, reply_markup=main_menu(KK))

    base_bot._analyze_upload = guarded_analyze_upload
    kazakh_ui._analyze_upload_kk = guarded_analyze_upload_kk
    _INSTALLED = True
    LOGGER.info("KORGAN document-neutral upload follow-up guard installed")
