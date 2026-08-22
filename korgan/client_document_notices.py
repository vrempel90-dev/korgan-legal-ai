"""Request-atomic checklist and generation-progress notices."""

from __future__ import annotations

from typing import Any

from korgan.client_document_feedback_hotfix import checklist_text, progress_text
from korgan.request_scope import document_request_lock


async def send_checklist_once(message: Any, state: Any, kind: str) -> bool:
    """Validate, mark and send a checklist in the same request-switch critical section."""
    async with document_request_lock(state):
        data = await state.get_data()
        request_id = str(data.get("request_id") or "")
        if not request_id or str(data.get("request_kind") or "") != kind:
            return False
        if (
            str(data.get("client_checklist_request_id") or "") == request_id
            and str(data.get("client_checklist_kind") or "") == kind
        ):
            return False
        language = "kk" if str(data.get("language") or "ru") == "kk" else "ru"
        # Mark while holding the same lock used to replace the request. The send
        # remains inside the lock, so a newer request cannot become active between
        # validation and Telegram delivery.
        await state.update_data(client_checklist_request_id=request_id, client_checklist_kind=kind)
        await message.answer(checklist_text(kind, language))
        return True


async def send_progress_once(message: Any, state: Any, kind: str) -> bool:
    """Send one authorized progress notice atomically for the current request."""
    async with document_request_lock(state):
        data = await state.get_data()
        request_id = str(data.get("request_id") or "")
        if not request_id or str(data.get("request_kind") or "") != kind:
            return False
        if (
            str(data.get("generation_progress_request_id") or "") == request_id
            and str(data.get("generation_progress_kind") or "") == kind
        ):
            return False
        language = "kk" if str(data.get("language") or "ru") == "kk" else "ru"
        await state.update_data(
            generation_progress_request_id=request_id,
            generation_progress_kind=kind,
        )
        await message.answer(progress_text(kind, language))
        return True
