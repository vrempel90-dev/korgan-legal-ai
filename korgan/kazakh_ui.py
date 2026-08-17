from __future__ import annotations

import io
import logging

from aiogram import F, Router
from aiogram.filters import BaseFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove

from korgan import bot as base_bot
from korgan.claim_intent import is_claim_drafting_request
from korgan.contract_intent import is_contract_drafting_request
from korgan.i18n import KK, RU, button, normalize_language, tr
from korgan.response_intent import is_response_to_claim_request
from korgan.ui import documents_menu, language_menu, main_menu

LOGGER = logging.getLogger(__name__)
router = Router(name="korgan-kazakh-ui")


class KazakhLanguage(BaseFilter):
    async def __call__(self, event: Message | CallbackQuery, state: FSMContext) -> bool:
        return normalize_language((await state.get_data()).get("language", RU)) == KK


class KazakhLegalText(BaseFilter):
    async def __call__(self, message: Message, state: FSMContext) -> bool:
        if not message.text or message.text.startswith("/"):
            return False
        data = await state.get_data()
        if normalize_language(data.get("language", RU)) != KK:
            return False
        if data.get("mode") in {"universal_claim_waiting", "contract_details", "response_details"}:
            return False
        if is_claim_drafting_request(message.text):
            return False
        if is_contract_drafting_request(message.text) or is_response_to_claim_request(message.text):
            return False
        return True


async def _save_text_as_fact(state: FSMContext, text: str) -> None:
    value = (text or "").strip()
    if not value:
        return
    data = await state.get_data()
    facts = list(data.get("facts", []) or [])
    if not facts or str(facts[-1]).strip() != value:
        facts.append(value)
    await state.update_data(facts=facts[-20:])


async def _analyze_upload_kk(
    message: Message,
    state: FSMContext,
    data: bytes,
    filename: str,
    mime_type: str | None,
) -> None:
    service = base_bot.service
    if service is None:
        return
    await message.bot.send_chat_action(message.chat.id, "typing")
    try:
        extracted = await service.extract_document(data, filename, mime_type)
    except ValueError as exc:
        # Supported formats are the same; keep the failure useful in Kazakh.
        LOGGER.info("Kazakh upload rejected filename=%s error=%s", filename, exc)
        await message.answer(
            "PDF, DOCX, TXT, JPG, JPEG, PNG және WEBP форматтары қолдау табады.",
            reply_markup=main_menu(KK),
        )
        return
    except Exception:
        LOGGER.exception("Kazakh document analysis failed")
        await message.answer(tr(KK, "upload_error"), reply_markup=main_menu(KK))
        return

    count = await base_bot._save_document(state, extracted)
    preview = extracted.as_context()
    await message.answer(
        tr(KK, "upload_ok", count=count, preview=preview[:3200]),
        reply_markup=main_menu(KK),
    )


@router.message(KazakhLanguage(), F.photo)
async def photo_kk(message: Message, state: FSMContext) -> None:
    photo = message.photo[-1]
    stream = io.BytesIO()
    await message.bot.download(photo, destination=stream)
    await _analyze_upload_kk(message, state, stream.getvalue(), f"photo_{photo.file_unique_id}.jpg", "image/jpeg")


@router.message(KazakhLanguage(), F.document)
async def document_kk(message: Message, state: FSMContext) -> None:
    document = message.document
    filename = document.file_name or f"document_{document.file_unique_id}"
    stream = io.BytesIO()
    await message.bot.download(document, destination=stream)
    await _analyze_upload_kk(message, state, stream.getvalue(), filename, document.mime_type)


@router.message(KazakhLanguage(), F.text == button(KK, "consultation"))
async def consultation_button_kk(message: Message, state: FSMContext) -> None:
    await state.update_data(mode="consultation")
    await message.answer(tr(KK, "consult_prompt"), reply_markup=main_menu(KK))


@router.message(KazakhLanguage(), F.text == button(KK, "document"))
async def document_button_kk(message: Message, state: FSMContext) -> None:
    await state.update_data(mode="main")
    await message.answer(tr(KK, "documents"), parse_mode="HTML", reply_markup=documents_menu(KK))


@router.message(KazakhLanguage(), F.text == button(KK, "prices"))
async def prices_button_kk(message: Message, state: FSMContext) -> None:
    await state.update_data(mode="main")
    await message.answer(tr(KK, "prices"), reply_markup=main_menu(KK))


@router.message(KazakhLanguage(), F.text == button(KK, "case"))
async def case_button_kk(message: Message, state: FSMContext) -> None:
    await state.update_data(mode="main")
    data = await state.get_data()
    await message.answer(
        tr(KK, "case_summary", docs=len(data.get("documents", []) or []), facts=len(data.get("facts", []) or [])),
        reply_markup=main_menu(KK),
    )


@router.message(KazakhLanguage(), F.text == button(KK, "lawyer"))
async def lawyer_button_kk(message: Message, state: FSMContext) -> None:
    await state.update_data(mode="main")
    await message.answer(tr(KK, "lawyer"), reply_markup=main_menu(KK))


@router.message(KazakhLanguage(), F.text == button(KK, "help"))
async def help_button_kk(message: Message, state: FSMContext) -> None:
    await state.update_data(mode="main")
    await message.answer(tr(KK, "help"), reply_markup=main_menu(KK))


@router.message(KazakhLanguage(), F.text == button(KK, "support"))
async def support_button_kk(message: Message, state: FSMContext) -> None:
    await state.update_data(mode="main")
    await message.answer(tr(KK, "support"), reply_markup=main_menu(KK))


@router.message(KazakhLanguage(), F.text == button(KK, "feedback"))
async def feedback_button_kk(message: Message, state: FSMContext) -> None:
    await state.update_data(mode="main")
    await message.answer(tr(KK, "feedback"), reply_markup=main_menu(KK))


@router.message(KazakhLanguage(), F.text == button(KK, "language"))
async def language_button_kk(message: Message) -> None:
    await message.answer(tr(KK, "choose_language"), reply_markup=language_menu())


@router.message(KazakhLanguage(), F.text == button(KK, "delete"))
async def delete_button_kk(message: Message, state: FSMContext) -> None:
    await state.set_data({"language": KK, "language_selected": True, "documents": [], "facts": [], "mode": "main", "terms_accepted": False})
    await message.answer(tr(KK, "deleted"), reply_markup=ReplyKeyboardRemove())


@router.callback_query(KazakhLanguage(), F.data == "menu:main")
async def main_callback_kk(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.update_data(mode="main")
    if callback.message is not None:
        await callback.message.answer(tr(KK, "main"), parse_mode="HTML", reply_markup=main_menu(KK))


@router.callback_query(KazakhLanguage(), F.data == "doc:claim")
async def claim_callback_kk(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message is not None:
        from korgan.universal_claim_runtime import _generate_now
        await _generate_now(callback.message, state)


@router.callback_query(KazakhLanguage(), F.data == "doc:contract")
async def contract_callback_kk(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.update_data(mode="contract_details")
    if callback.message is not None:
        await callback.message.answer(tr(KK, "contract_prompt"), reply_markup=main_menu(KK))


@router.callback_query(KazakhLanguage(), F.data == "doc:response")
async def response_callback_kk(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.update_data(mode="response_details")
    if callback.message is not None:
        await callback.message.answer(tr(KK, "response_prompt"), reply_markup=main_menu(KK))


@router.message(KazakhLegalText(), F.text)
async def legal_question_kk(message: Message, state: FSMContext) -> None:
    service = base_bot.service
    if service is None or not message.text:
        return

    await _save_text_as_fact(state, message.text)
    await state.update_data(mode="main")
    context = await base_bot._case_context(state)
    await message.bot.send_chat_action(message.chat.id, "typing")
    try:
        answer, urls = await service.consult(message.text, case_context=context, language=KK)
    except Exception:
        LOGGER.exception("Kazakh consultation failed")
        await message.answer(tr(KK, "consult_error"), reply_markup=main_menu(KK))
        return

    if urls:
        cited = base_bot.extract_cited_articles(answer)
        if cited:
            refreshed = await state.get_data()
            previous = list(refreshed.get("consulted_articles", []) or [])
            for item in cited:
                if item not in previous:
                    previous.append(item)
            await state.update_data(consulted_articles=previous[-20:])

    sources = ""
    if urls:
        sources = "\n\n" + tr(KK, "sources") + "\n" + "\n".join(f"• {url}" for url in urls[:5])
    for part in base_bot._split(answer + sources):
        await message.answer(part, disable_web_page_preview=True, reply_markup=main_menu(KK))
