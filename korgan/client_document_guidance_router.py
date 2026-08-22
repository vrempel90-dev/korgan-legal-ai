"""Priority KK document callbacks that enter the canonical request-scoped intake."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import BaseFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from korgan.i18n import KK, normalize_language
from korgan.request_scope import start_new_document_request

router = Router(name="client-document-guidance-priority")


class _KazakhRequest(BaseFilter):
    """Match only a session whose selected client language is Kazakh."""

    async def __call__(self, callback: CallbackQuery, state: FSMContext) -> bool:
        return normalize_language(str((await state.get_data()).get("language", "ru"))) == KK


@router.callback_query(_KazakhRequest(), F.data == "doc:claim")
async def claim_callback_kk_guided(callback: CallbackQuery, state: FSMContext) -> None:
    """Start a fresh KK claim request through the canonical intake helper."""
    await callback.answer()
    if callback.message is None:
        return
    from korgan import universal_claim_runtime

    await start_new_document_request(state, kind="claim", mode="universal_claim_waiting")
    await universal_claim_runtime.begin_claim_request(callback.message, state)


@router.callback_query(_KazakhRequest(), F.data == "doc:contract")
async def contract_callback_kk_guided(callback: CallbackQuery, state: FSMContext) -> None:
    """Start a fresh KK contract request through the canonical intake helper."""
    await callback.answer()
    if callback.message is None:
        return
    from korgan import universal_document_runtime

    await start_new_document_request(state, kind="contract", mode="contract_details")
    await universal_document_runtime._ask_contract(callback.message, state)


@router.callback_query(_KazakhRequest(), F.data == "doc:response")
async def response_callback_kk_guided(callback: CallbackQuery, state: FSMContext) -> None:
    """Start a fresh KK response request through the canonical intake helper."""
    await callback.answer()
    if callback.message is None:
        return
    from korgan import universal_document_runtime

    await start_new_document_request(state, kind="response", mode="response_details")
    await universal_document_runtime._ask_response(callback.message, state)
