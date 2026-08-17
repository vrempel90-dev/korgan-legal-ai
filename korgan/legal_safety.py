from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    ReplyKeyboardRemove,
    TelegramObject,
)

from korgan.i18n import KK, RU, normalize_language, tr
from korgan.ui import main_menu

LOGGER = logging.getLogger(__name__)
router = Router(name="korgan-legal-safety")

TERMS_VERSION = "2026-08-16-v1"

_TERMS = {
    RU: (
        "🛡 <b>Условия использования KORGAN Legal AI</b>\n\n"
        "Перед использованием подтвердите условия.\n\n"
        "1. <b>KORGAN — система искусственного интеллекта.</b> Ответы и документы формируются автоматически на основании данных пользователя и найденных источников. KORGAN не является судом, государственным органом и не гарантирует принятие документа или исход дела.\n\n"
        "2. <b>Факты предоставляет пользователь.</b> Вы подтверждаете достоверность сообщаемых сведений настолько, насколько вам известно, и наличие законных оснований передавать содержащиеся в них персональные данные. KORGAN не должен создавать отсутствующие факты или доказательства.\n\n"
        "3. <b>Правовые нормы проверяются.</b> Значимые правовые выводы, сроки, госпошлина и подсудность должны подтверждаться официальными источниками. Неподтверждённые выводы не выдаются клиенту как установленные.\n\n"
        "4. <b>Документы являются проектами.</b> Перед подачей в суд или государственный орган проверьте Ф.И.О./ИИН/БИН, адреса, даты, суммы, доказательства, требования, подсудность и госпошлину. Для сложных или спорных дел рекомендуется дополнительная проверка квалифицированным юристом или адвокатом.\n\n"
        "5. <b>Нет гарантии результата.</b> Итог зависит от доказательств, позиции другой стороны, процессуальных действий и решения суда/органа. Это условие не ограничивает права пользователя, которые не могут быть ограничены законом.\n\n"
        "6. <b>Персональные данные.</b> Нажимая «Принимаю», вы даёте согласие на обработку переданных данных в объёме, необходимом для консультации, анализа материалов, формирования документов и безопасности сервиса. Данные текущего дела можно удалить через кнопку удаления данных.\n\n"
        "7. <b>Запрещено</b> использовать KORGAN для подделки доказательств, мошенничества, выдачи себя за другое лицо или иной незаконной деятельности.\n\n"
        f"Версия условий: <code>{TERMS_VERSION}</code>"
    ),
    KK: (
        "🛡 <b>KORGAN Legal AI пайдалану шарттары</b>\n\n"
        "Пайдалануды бастамас бұрын шарттарды растаңыз.\n\n"
        "1. <b>KORGAN — жасанды интеллект жүйесі.</b> Жауаптар мен құжаттар пайдаланушы берген деректер және табылған дереккөздер негізінде автоматты түрде жасалады. KORGAN сот немесе мемлекеттік орган болып табылмайды және құжаттың қабылдануына не істің нәтижесіне кепілдік бермейді.\n\n"
        "2. <b>Фактілерді пайдаланушы береді.</b> Сіз берген мәліметтердің өзіңізге белгілі дәрежеде дұрыс екенін және олардың құрамындағы дербес деректерді беруге заңды негізіңіз бар екенін растайсыз. KORGAN материалдарда жоқ фактілерді немесе дәлелдемелерді ойдан қоспауға тиіс.\n\n"
        "3. <b>Құқықтық нормалар тексеріледі.</b> Маңызды құқықтық қорытындылар, мерзімдер, мемлекеттік баж және соттылық ресми дереккөздермен расталуға тиіс. Расталмаған қорытындылар клиентке анықталған факт ретінде берілмейді.\n\n"
        "4. <b>Құжаттар жоба болып табылады.</b> Сотқа немесе мемлекеттік органға берер алдында аты-жөнін/ЖСН/БСН, мекенжайларды, күндерді, сомаларды, дәлелдемелерді, талаптарды, соттылықты және мемлекеттік бажды тексеріңіз. Күрделі немесе даулы істерде білікті заңгердің немесе адвокаттың қосымша тексеруі ұсынылады.\n\n"
        "5. <b>Нәтижеге кепілдік жоқ.</b> Нәтиже дәлелдемелерге, екінші тараптың ұстанымына, процестік әрекеттерге және соттың/органның шешіміне байланысты. Бұл шарт заң бойынша шектелмейтін пайдаланушы құқықтарын шектемейді.\n\n"
        "6. <b>Дербес деректер.</b> «Қабылдаймын» батырмасын басу арқылы сіз кеңес беру, материалдарды талдау, құжаттарды қалыптастыру және сервистің қауіпсіздігін қамтамасыз ету үшін қажетті көлемде берілген деректерді өңдеуге келісім бересіз. Ағымдағы іс деректерін жою батырмасы арқылы өшіруге болады.\n\n"
        "7. <b>Тыйым салынады:</b> KORGAN-ды дәлелдемелерді қолдан жасау, алаяқтық, басқа тұлғаның атынан әрекет ету немесе өзге заңсыз қызмет үшін пайдалану.\n\n"
        f"Шарттар нұсқасы: <code>{TERMS_VERSION}</code>"
    ),
}

_PRIVACY = {
    RU: (
        "🔐 <b>Персональные данные и конфиденциальность</b>\n\n"
        "KORGAN обрабатывает сведения, которые пользователь сам отправляет в чат или прикрепляет к делу, а также технические идентификаторы, необходимые для работы Telegram-сессии и фиксации согласия.\n\n"
        "Цель обработки: юридическая консультация, извлечение фактов из материалов, формирование документов, безопасность сервиса и подтверждение принятия условий.\n\n"
        "Материалы текущего дела можно удалить через кнопку «🗑 Удалить мои данные»."
    ),
    KK: (
        "🔐 <b>Дербес деректер және құпиялылық</b>\n\n"
        "KORGAN пайдаланушы чатқа өзі жіберген немесе іске тіркеген мәліметтерді, сондай-ақ Telegram-сессиясының жұмысы және келісімді тіркеу үшін қажетті техникалық идентификаторларды өңдейді.\n\n"
        "Өңдеу мақсаты: заңдық кеңес беру, материалдардан фактілерді шығару, құжаттарды қалыптастыру, сервистің қауіпсіздігін қамтамасыз ету және шарттарды қабылдауды растау.\n\n"
        "Ағымдағы іс материалдарын «🗑 Деректерімді жою» батырмасы арқылы өшіруге болады."
    ),
}

_CLAIM_CONFIRM = {
    RU: (
        "⚠️ <b>Перед формированием судебного документа</b>\n\n"
        "Подтвердите, что вы проверите персональные данные и факты, понимаете проектный характер документа и самостоятельно принимаете решение о его подаче.\n\n"
        "После подтверждения KORGAN без анкеты проверит правовую основу и сформирует файл .docx."
    ),
    KK: (
        "⚠️ <b>Сот құжатын қалыптастыру алдында</b>\n\n"
        "Дербес деректер мен фактілерді тексеретініңізді, құжаттың жоба екенін түсінетініңізді және оны сотқа беру туралы шешімді өзіңіз қабылдайтыныңызды растаңыз.\n\n"
        "Растағаннан кейін KORGAN сауалнама толтырмай-ақ құқықтық негізді тексеріп, .docx файлын қалыптастырады."
    ),
}

# Backward-compatible Russian constants.
TERMS_TEXT = _TERMS[RU]
PRIVACY_TEXT = _PRIVACY[RU]
CLAIM_CONFIRM_TEXT = _CLAIM_CONFIRM[RU]


def terms_text(language: str = RU) -> str:
    return _TERMS[normalize_language(language)]


def privacy_text(language: str = RU) -> str:
    return _PRIVACY[normalize_language(language)]


def claim_confirm_text(language: str = RU) -> str:
    return _CLAIM_CONFIRM[normalize_language(language)]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def terms_keyboard(language: str = RU) -> InlineKeyboardMarkup:
    lang = normalize_language(language)
    if lang == KK:
        accept, privacy, decline = "✅ Шарттарды қабылдаймын", "🔐 Құпиялылық", "❌ Қабылдамаймын"
    else:
        accept, privacy, decline = "✅ Принимаю условия", "🔐 Конфиденциальность", "❌ Не принимаю"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=accept, callback_data="terms:accept")],
            [InlineKeyboardButton(text=privacy, callback_data="terms:privacy")],
            [InlineKeyboardButton(text=decline, callback_data="terms:decline")],
        ]
    )


def claim_confirmation_keyboard(language: str = RU) -> InlineKeyboardMarkup:
    lang = normalize_language(language)
    if lang == KK:
        confirm, cancel = "✅ Келісемін, құжатты дайындау", "↩️ Болдырмау"
    else:
        confirm, cancel = "✅ Согласен, сформировать документ", "↩️ Отмена"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=confirm, callback_data="claim:confirm")],
            [InlineKeyboardButton(text=cancel, callback_data="claim:cancel")],
        ]
    )


async def has_current_consent(state: FSMContext | None) -> bool:
    if state is None:
        return False
    data = await state.get_data()
    return bool(data.get("terms_accepted")) and data.get("terms_version") == TERMS_VERSION


async def show_terms(message: Message, language: str = RU) -> None:
    lang = normalize_language(language)
    await message.answer(terms_text(lang), parse_mode="HTML", reply_markup=ReplyKeyboardRemove())
    await message.answer(
        "Жалғастыру үшін әрекетті таңдаңыз:" if lang == KK else "Чтобы продолжить работу с KORGAN, выберите действие:",
        reply_markup=terms_keyboard(lang),
    )


class ConsentMiddleware(BaseMiddleware):
    """Fail closed: no legal processing before the current terms are accepted."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message):
            return await handler(event, data)

        text = (event.text or "").strip()
        if text.startswith(("/start", "/terms", "/privacy", "/language", "/ru", "/kk")):
            return await handler(event, data)

        state = data.get("state")
        if await has_current_consent(state):
            return await handler(event, data)

        lang = RU
        if state is not None:
            lang = normalize_language((await state.get_data()).get("language", RU))
        await show_terms(event, lang)
        return None


@router.callback_query(F.data == "terms:accept")
async def accept_terms(callback: CallbackQuery, state: FSMContext) -> None:
    accepted_at = utc_now_iso()
    data = await state.get_data()
    lang = normalize_language(data.get("language", RU))
    await state.update_data(
        language=lang,
        language_selected=True,
        documents=list(data.get("documents", []) or []),
        facts=list(data.get("facts", []) or []),
        terms_accepted=True,
        terms_version=TERMS_VERSION,
        terms_accepted_at=accepted_at,
        privacy_consent=True,
    )
    LOGGER.info("LEGAL_TERMS_ACCEPTED version=%s telegram_user_id=%s accepted_at=%s language=%s", TERMS_VERSION, callback.from_user.id, accepted_at, lang)
    await callback.answer("Шарттар қабылданды" if lang == KK else "Условия приняты")
    chat_id = getattr(getattr(callback.message, "chat", None), "id", callback.from_user.id)
    await callback.bot.send_message(
        chat_id,
        ("✅ Шарттар қабылданды.\n\n" if lang == KK else "✅ Условия приняты.\n\n") + tr(lang, "welcome"),
        parse_mode="HTML",
        reply_markup=main_menu(lang),
    )


@router.callback_query(F.data == "terms:privacy")
async def privacy_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    lang = normalize_language((await state.get_data()).get("language", RU))
    chat_id = getattr(getattr(callback.message, "chat", None), "id", callback.from_user.id)
    await callback.bot.send_message(chat_id, privacy_text(lang), parse_mode="HTML", reply_markup=terms_keyboard(lang))


@router.callback_query(F.data == "terms:decline")
async def decline_terms(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    lang = normalize_language(data.get("language", RU))
    await state.set_data({"language": lang, "language_selected": True, "documents": [], "facts": [], "terms_accepted": False})
    LOGGER.info("LEGAL_TERMS_DECLINED version=%s telegram_user_id=%s", TERMS_VERSION, callback.from_user.id)
    await callback.answer("Шарттар қабылданбады" if lang == KK else "Условия не приняты")
    chat_id = getattr(getattr(callback.message, "chat", None), "id", callback.from_user.id)
    text = (
        "Шарттарды қабылдамай KORGAN заңдық сұраулар мен құжаттарды өңдемейді. Кез келген уақытта /start арқылы қайта оралуға болады."
        if lang == KK
        else "Без принятия условий KORGAN не будет обрабатывать юридические запросы и документы. Вы можете вернуться к /start в любое время."
    )
    await callback.bot.send_message(chat_id, text, reply_markup=ReplyKeyboardRemove())


@router.callback_query(F.data == "claim:cancel")
async def cancel_claim(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(claim_confirmation_pending=False)
    lang = normalize_language((await state.get_data()).get("language", RU))
    await callback.answer("Қалыптастыру тоқтатылды" if lang == KK else "Формирование отменено")
    chat_id = getattr(getattr(callback.message, "chat", None), "id", callback.from_user.id)
    await callback.bot.send_message(
        chat_id,
        "Құжатты қалыптастыру тоқтатылды." if lang == KK else "Формирование документа отменено.",
        reply_markup=main_menu(lang),
    )


@router.callback_query(F.data == "claim:confirm")
async def confirm_claim(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    lang = normalize_language(data.get("language", RU))
    if not await has_current_consent(state):
        await callback.answer("Алдымен шарттарды қабылдаңыз" if lang == KK else "Сначала примите условия", show_alert=True)
        chat_id = getattr(getattr(callback.message, "chat", None), "id", callback.from_user.id)
        await callback.bot.send_message(chat_id, terms_text(lang), parse_mode="HTML", reply_markup=terms_keyboard(lang))
        return

    if not data.get("claim_confirmation_pending"):
        await callback.answer("Растау мерзімі өтті" if lang == KK else "Подтверждение устарело", show_alert=True)
        return

    confirmed_at = utc_now_iso()
    await state.update_data(claim_confirmation_pending=False, claim_warning_confirmed_at=confirmed_at, claim_warning_version=TERMS_VERSION)
    LOGGER.info("CLAIM_DRAFT_WARNING_ACCEPTED version=%s telegram_user_id=%s accepted_at=%s", TERMS_VERSION, callback.from_user.id, confirmed_at)
    await callback.answer("Қалыптастыруды бастаймын" if lang == KK else "Начинаю формирование")

    message = callback.message
    chat_id = getattr(getattr(message, "chat", None), "id", callback.from_user.id)
    if message is None:
        await callback.bot.send_message(
            chat_id,
            "Қалыптастыруды бастау мүмкін болмады. /menu жіберіп, қайталап көріңіз." if lang == KK else "Не удалось запустить формирование. Отправьте /menu и повторите.",
            reply_markup=main_menu(lang),
        )
        return

    try:
        # Always use the universal no-questionnaire production flow. Never fall
        # back to legacy field-by-field claim intake after confirmation.
        from korgan.universal_claim_runtime import _generate_now
        await _generate_now(message, state)  # type: ignore[arg-type]
    except Exception:
        LOGGER.exception("Confirmed claim generation failed")
        await callback.bot.send_message(
            chat_id,
            "Құжатты қалыптастыру мүмкін болмады. Іс материалдары сақталды; кейінірек қайталап көріңіз." if lang == KK else "Не удалось сформировать документ. Материалы дела сохранены; повторите попытку позже.",
            reply_markup=main_menu(lang),
        )
