from __future__ import annotations

import logging
import re

from aiogram import F, Router
from aiogram.filters import BaseFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from korgan import bot as base_bot
from korgan.i18n import KK, normalize_language
from korgan.pretrial_response import (
    build_pretrial_response_docx,
    is_pretrial_response_request,
    pretrial_response_quality_issues,
)
from korgan.ui import main_menu

LOGGER = logging.getLogger(__name__)
router = Router(name="korgan-pretrial-response")

# «Отзыв» is reserved for a court response to a claim. The pre-trial workflow
# uses «Ответ на претензию» in Russian. Reject the old mixed wording instead of
# letting it collide with another document category.
_LEGACY_MIXED_RU = re.compile(
    r"(?i)\bотзыв\w*\s+на\s+(?:досудебн\w*\s+)?претензи\w*\b"
)


class _Waiting(BaseFilter):
    async def __call__(self, message: Message, state: FSMContext) -> bool:
        data = await state.get_data()
        return data.get("mode") == "pretrial_response_waiting" and bool(message.text) and not message.text.startswith("/")


class _Intent(BaseFilter):
    async def __call__(self, message: Message, state: FSMContext) -> bool:
        data = await state.get_data()
        if data.get("mode") in {"consultation", "contract_details", "response_details", "pretrial_waiting"}:
            return False
        text = message.text or ""
        if _LEGACY_MIXED_RU.search(text):
            return False
        return is_pretrial_response_request(text)


def install_pretrial_response_transport() -> None:
    """Register generated filenames without changing the payment architecture."""
    from korgan import localized_transport, payment

    # New client-facing filename. Keep the old name recognized only for already
    # held/generated documents from previous deployments.
    localized_transport._DOCUMENT_KINDS["korgan_otvet_na_pretenziyu.docx"] = "pretrial_response"
    localized_transport._DOCUMENT_KINDS["korgan_otzyv_na_pretenziyu.docx"] = "pretrial_response"
    localized_transport._DOCUMENT_KINDS["korgan_sotqa_deyingi_talapqa_zhauap.docx"] = "pretrial_response"
    payment._KIND_RU["pretrial_response"] = "ответ на претензию"
    payment._KIND_KK["pretrial_response"] = "сотқа дейінгі талапқа жауап"

    original_caption = localized_transport._document_client_caption
    original_review = localized_transport._document_review_text

    def document_client_caption(kind: str, language: str) -> str:
        if kind != "pretrial_response":
            return original_caption(kind, language)
        if language == KK:
            return "✅ Сотқа дейінгі талапқа жауап Word (.docx) форматында дайын."
        return "✅ Ответ на претензию сформирован в Word (.docx)."

    def document_review_text(kind: str, language: str) -> str:
        if kind != "pretrial_response":
            return original_review(kind, language)
        if language == KK:
            return (
                "⚠️ Сотқа дейінгі талапқа жауапты кәсіби заңгерге тексертуге кеңес береміз.\n"
                "Тексеру ақылы. Қосымша қызметтер ақылы.\n"
                "Заңгерге жіберу керек пе?"
            )
        return (
            "⚠️ Рекомендуем проверить ответ на претензию у профессионального юриста.\n"
            "Проверка платная. Доп. услуги — платные.\n"
            "Передать юристу?"
        )

    localized_transport._document_client_caption = document_client_caption
    localized_transport._document_review_text = document_review_text


async def _lang(state: FSMContext) -> str:
    return normalize_language(str((await state.get_data()).get("language", "ru")))


async def _save_text(message: Message, state: FSMContext) -> None:
    if message.from_user is not None and message.from_user.is_bot:
        return
    text = (message.text or "").strip()
    if not text:
        return
    data = await state.get_data()
    facts = list(data.get("facts", []) or [])
    if not facts or str(facts[-1]).strip() != text:
        facts.append(text)
    await state.update_data(facts=facts[-20:])


def _looks_like_pretrial_materials(context: str) -> bool:
    text = " ".join((context or "").split()).lower()
    if not text:
        return False
    return bool(
        re.search(r"\bпретензи\w*\b|\bдосудебн\w*\s+требован\w*\b|\bсотқа\s+дейінгі\s+талап\w*", text)
        and re.search(r"\bтребован\w*\b|\bпрос\w*\b|\bоплат\w*\b|\bвзыск\w*\b|\bталап\w*\b", text)
    )


async def _ask_materials(message: Message, state: FSMContext, language: str) -> None:
    await state.update_data(mode="pretrial_response_waiting")
    if language == KK:
        text = (
            "🛡 Сотқа дейінгі талапқа жауап дайындау үшін талаптың өзін (PDF/DOCX/фото) жіберіңіз немесе негізгі талаптарын мәтінмен енгізіңіз.\n\n"
            "Мүмкін болса, бір хабарламада өз ұстанымыңызды, қандай фактілермен келіспейтініңізді және қандай дәлелдеріңіз бар екенін жазыңыз."
        )
    else:
        text = (
            "🛡 Чтобы подготовить ответ на претензию, пришлите саму претензию (PDF/DOCX/фото) или вставьте её основные требования текстом.\n\n"
            "Если можете, одним сообщением добавьте свою позицию: что признаёте или оспариваете, какие факты неверны и какие доказательства у вас есть."
        )
    await message.answer(text, reply_markup=main_menu(language))


async def _generate(message: Message, state: FSMContext) -> None:
    await _save_text(message, state)
    language = await _lang(state)
    context = await base_bot._case_context(state)
    menu = main_menu(language)

    if not _looks_like_pretrial_materials(context):
        await _ask_materials(message, state, language)
        return

    service = base_bot.service
    research_method = getattr(service, "research_pretrial_response", None) if service is not None else None
    draft_method = getattr(service, "draft_pretrial_response", None) if service is not None else None
    if research_method is None or draft_method is None:
        await message.answer(
            "Сотқа дейінгі талапқа жауап модулі жүктелмеді."
            if language == KK
            else "Модуль ответа на претензию не загружен.",
            reply_markup=menu,
        )
        return

    await state.update_data(mode="main")
    await message.answer(
        "Сотқа дейінгі талапты талдап, құқықтық негізді тексеріп, жауапты дайындап жатырмын…"
        if language == KK
        else "Анализирую претензию, проверяю правовую основу и формирую ответ…",
        reply_markup=menu,
    )
    await message.bot.send_chat_action(message.chat.id, "typing")

    try:
        research = await research_method(context, language=language)
        draft = await draft_method(context, research, language=language)
        issues = pretrial_response_quality_issues(draft, research)
        file_bytes = build_pretrial_response_docx(draft, language=language)
    except Exception:
        LOGGER.exception("Pretrial response generation failed")
        await message.answer(
            "Сотқа дейінгі талапқа жауапты қауіпсіз қалыптастыру мүмкін болмады. Материалдарды тексеріп, қайта көріңіз."
            if language == KK
            else "Не удалось безопасно сформировать ответ на претензию. Проверьте материалы и повторите запрос.",
            reply_markup=menu,
        )
        return

    if issues:
        LOGGER.warning("PRETRIAL_RESPONSE_PRELIMINARY issues=%s", issues[:6])
        caption = (
            "✅ Сотқа дейінгі талапқа жауаптың жобасы Word (.docx) форматында дайын. Жіберер алдында деректемелер мен позицияны тексеріңіз."
            if language == KK
            else "✅ Проект ответа на претензию сформирован в Word (.docx). Перед направлением проверьте реквизиты и позицию."
        )
    else:
        caption = (
            "✅ Сотқа дейінгі талапқа жауап Word (.docx) форматында дайын."
            if language == KK
            else "✅ Ответ на претензию сформирован в Word (.docx)."
        )

    filename = (
        "KORGAN_sotqa_deyingi_talapqa_zhauap.docx"
        if language == KK
        else "KORGAN_otvet_na_pretenziyu.docx"
    )
    await message.answer_document(
        BufferedInputFile(file_bytes, filename=filename),
        caption=caption,
        reply_markup=menu,
    )


@router.callback_query(F.data == "doc:pretrial_response")
async def pretrial_response_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message is not None:
        await _generate(callback.message, state)


@router.message(_Waiting(), F.text)
async def pretrial_response_waiting(message: Message, state: FSMContext) -> None:
    await _generate(message, state)


@router.message(_Intent(), F.text)
async def pretrial_response_natural(message: Message, state: FSMContext) -> None:
    await _generate(message, state)
