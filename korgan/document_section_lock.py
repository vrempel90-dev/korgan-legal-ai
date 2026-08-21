from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Filter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from korgan.request_scope import active_document_kind, is_main_menu_text

router = Router(name="document-section-lock")

_WAITING_MODE_BY_KIND = {
    "claim": "universal_claim_waiting",
    "pretrial": "pretrial_waiting",
    "pretrial_response": "pretrial_response_waiting",
    "response": "response_details",
    "contract": "contract_details",
}


class SelectedDocumentSection(Filter):
    """Own text while a document button's request is waiting for case data."""

    async def __call__(self, message: Message, state: FSMContext):
        text = message.text or ""
        if not text or text.startswith("/") or is_main_menu_text(text):
            return False

        data = await state.get_data()
        kind = active_document_kind(data)
        if kind is None:
            return False

        # Only intercept the data-entry phase. Verification/payment/other special
        # states retain their own dedicated handlers.
        if data.get("mode") != _WAITING_MODE_BY_KIND.get(kind):
            return False

        return {"selected_document_kind": kind}


@router.message(SelectedDocumentSection(), F.text)
async def route_selected_document_section(
    message: Message,
    state: FSMContext,
    selected_document_kind: str,
) -> None:
    """Route all case text only to the section explicitly selected by its button.

    The selected button is the source of truth. We deliberately do not inspect
    legal nouns such as "договор", "претензия", "иск" or "отзыв" in case facts:
    those words describe the dispute and must never change the workflow.
    Switching document type is possible only through another document button.
    """
    # Lazy imports avoid changing production initialization order.
    from korgan import pretrial_response_runtime, pretrial_runtime, universal_claim_runtime, universal_document_runtime

    if selected_document_kind == "claim":
        await universal_claim_runtime.claim_description(message, state)
        return
    if selected_document_kind == "pretrial":
        await pretrial_runtime.pretrial_waiting(message, state)
        return
    if selected_document_kind == "pretrial_response":
        await pretrial_response_runtime.pretrial_response_waiting(message, state)
        return
    if selected_document_kind == "response":
        await universal_document_runtime.response_details(message, state)
        return
    if selected_document_kind == "contract":
        await universal_document_runtime.contract_details(message, state)
        return
