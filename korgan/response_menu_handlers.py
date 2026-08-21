from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import BaseFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from korgan.response_intent import is_response_to_claim_request
from korgan.ui import main_menu

router = Router(name="korgan-response-to-claim")


class ResponseDetailsFilter(BaseFilter):
    async def __call__(self, message: Message, state: FSMContext) -> bool:
        data = await state.get_data()
        return data.get("mode") == "response_details" and bool(message.text) and not message.text.startswith("/")


class ResponseRequestFilter(BaseFilter):
    async def __call__(self, message: Message, state: FSMContext) -> bool:
        data = await state.get_data()
        if data.get("mode") in {"consultation", "contract_details"}:
            return False
        return is_response_to_claim_request(message.text)


async def _save_user_text(message: Message, state: FSMContext) -> None:
    if message.from_user is not None and message.from_user.is_bot:
        return
    text = (message.text or "").strip()
    if not text or text in {"📄 Документ", "🛡 Отзыв на иск"}:
        return
    data = await state.get_data()
    facts = list(data.get("facts", []) or [])
    if text not in facts[-3:]:
        facts.append(text)
    await state.update_data(facts=facts[-20:])


async def _ask_for_claim(message: Message, state: FSMContext) -> None:
    await state.update_data(mode="response_details")
    await message.answer(
        "🛡 Чтобы подготовить отзыв на иск, пришлите сам иск (PDF/DOCX/фото) или вставьте его основные требования текстом.\n\n"
        "Если можете, сразу добавьте одним сообщением:\n"
        "• что именно вы признаёте или оспариваете;\n"
        "• какие факты истца неверны;\n"
        "• какие у вас есть доказательства, платежи, переписка или документы;\n"
        "• наименование суда и номер дела, если известны.\n\n"
        "KORGAN разберёт требования истца, проверит актуальные нормы РК и сформирует отзыв в Word (.docx).",
        reply_markup=main_menu(),
    )


async def _send_response_as_word(message: Message, state: FSMContext) -> None:
    from korgan import universal_document_runtime

    await universal_document_runtime._send_response(message, state)


@router.message(ResponseDetailsFilter())
async def response_details_reply(message: Message, state: FSMContext) -> None:
    from korgan.request_scope import current_request_id, start_new_document_request

    if not await current_request_id(state, "response"):
        await start_new_document_request(state, kind="response", mode="main")
    await _save_user_text(message, state)
    await state.update_data(mode="main")
    await _send_response_as_word(message, state)


@router.message(ResponseRequestFilter())
async def natural_language_response_request(message: Message, state: FSMContext) -> None:
    from korgan.request_scope import start_new_document_request

    await start_new_document_request(state, kind="response", mode="main")
    await _send_response_as_word(message, state)


@router.callback_query(F.data == "doc:response")
async def document_response_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message is None:
        return
    from korgan.request_scope import start_new_document_request

    await start_new_document_request(state, kind="response", mode="response_details")
    await _ask_for_claim(callback.message, state)
