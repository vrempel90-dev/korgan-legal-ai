from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import BaseFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from korgan import bot as base_bot
from korgan.claim_intent import is_claim_drafting_request
from korgan.config import get_settings
from korgan.consultation_quota import (
    ConsultationOrder,
    accept_consultation_receipt,
    consultation_payment_markup,
    create_consultation_order,
    get_consultation_order,
    mark_consultation_consumed,
    release_free_consultation,
    reserve_free_consultation,
    retry_markup,
    verify_consultation_signature,
)
from korgan.kaspi_ofd import KaspiOFDVerificationError, fetch_kaspi_ofd_receipt, fiscal_receipt_issues
from korgan.legal_corpus import extract_cited_articles
from korgan.request_scope import (
    consultation_request_is_current,
    document_request_lock,
    start_new_consultation_request,
)

LOGGER = logging.getLogger(__name__)
router = Router(name="korgan-consultation-quota-runtime")

_DELIVERED = "delivered"
_FAILED = "failed"
_STALE = "stale"


class ConsultationReceiptFilter(BaseFilter):
    async def __call__(self, message: Message, state: FSMContext) -> bool:
        if not get_settings().consultation_limit_enabled:
            return False
        data = await state.get_data()
        return data.get("mode") == "consultation_payment_receipt" and bool(message.photo or message.document)


class ConsultationReceiptTextFilter(BaseFilter):
    async def __call__(self, message: Message, state: FSMContext) -> bool:
        if not get_settings().consultation_limit_enabled:
            return False
        data = await state.get_data()
        return data.get("mode") == "consultation_payment_receipt" and bool(message.text)


class LimitedConsultationFilter(BaseFilter):
    """Match only text that would otherwise fall through to base_bot.legal_question()."""

    async def __call__(self, message: Message, state: FSMContext) -> bool:
        settings = get_settings()
        if not settings.consultation_limit_enabled or not message.text or message.text.startswith("/"):
            return False

        data = await state.get_data()
        mode = data.get("mode")
        if mode in {"verification_gate", "claim_details", "consultation_payment_receipt"}:
            return False

        explicit_consultation = mode == "consultation"
        if is_claim_drafting_request(message.text) and not explicit_consultation:
            return False
        return True


def _parse_callback(data: str, action: str) -> tuple[int, str] | None:
    parts = data.split(":")
    if len(parts) != 4 or parts[:2] != ["cp", action]:
        return None
    try:
        return int(parts[2]), parts[3]
    except ValueError:
        return None


def _consultation_payment_text_ofd(language: str, free_limit: int, amount_kzt: int) -> str:
    amount = f"{amount_kzt:,}".replace(",", " ")
    if language == "kk":
        return (
            "⚖️ Бүгінгі тегін кеңес лимиті аяқталды\n\n"
            f"Бүгін {free_limit} тегін кеңестің {free_limit}-і пайдаланылды.\n"
            f"Келесі бір кеңес — {amount} ₸.\n\n"
            "Сұрағыңыз сақталды. Kaspi арқылы төлеңіз, содан кейін «✅ Төледім» түймесін басыңыз.\n\n"
            "Фискалдық чектегі QR-кодты сканерлеп, ашылған receipt.kaspi.kz сілтемесін жіберіңіз. "
            "KORGAN төлемді Kaspi ОФД арқылы тексереді; AI төлем туралы шешім қабылдамайды."
        )
    return (
        "⚖️ Бесплатный лимит консультаций на сегодня исчерпан\n\n"
        f"Использовано: {free_limit} из {free_limit} бесплатных консультаций.\n"
        f"Следующая одна консультация — {amount} ₸.\n\n"
        "Ваш вопрос сохранён. Оплатите через Kaspi, затем нажмите «✅ Я оплатил».\n\n"
        "Отсканируйте QR на фискальном чеке и пришлите открывшуюся ссылку receipt.kaspi.kz. "
        "KORGAN проверит оплату через Kaspi ОФД; AI не принимает решение об оплате."
    )


def _fiscal_qr_instruction(language: str) -> str:
    if language == "kk":
        return (
            "🔎 Фискалдық чектегі QR-кодты телефон камерасымен сканерлеңіз және ашылған "
            "receipt.kaspi.kz сілтемесін осы чатқа жіберіңіз. Фото/PDF төлемді растамайды."
        )
    return (
        "🔎 Отсканируйте QR именно на фискальном чеке камерой телефона и отправьте сюда "
        "открывшуюся ссылку receipt.kaspi.kz. Фото/PDF не подтверждают оплату."
    )


async def _remember_consultation_result(
    state: FSMContext,
    answer: str,
    urls: list[str],
    consultation_request_id: str,
) -> bool:
    """Atomically persist citation hints only for the still-active consultation."""
    cited = extract_cited_articles(answer) if urls else []
    async with document_request_lock(state):
        refreshed = await state.get_data()
        if str(refreshed.get("consultation_request_id") or "") != consultation_request_id:
            return False
        if not cited:
            return True
        previous = list(refreshed.get("consulted_articles", []) or [])
        for item in cited:
            if item not in previous:
                previous.append(item)
        await state.update_data(consulted_articles=previous[-20:])
        return True


async def _send_consultation_answer(
    message: Message,
    state: FSMContext,
    *,
    question: str,
    case_context: str,
    language: str,
    consultation_request_id: str | None = None,
) -> str:
    """Generate and deliver only while this consultation still owns the session."""
    service = base_bot.service
    if service is None:
        await message.answer("Юридический AI-сервис временно недоступен.")
        return _FAILED

    if not consultation_request_id:
        consultation_request_id = await start_new_consultation_request(state)

    await message.bot.send_chat_action(message.chat.id, "typing")
    try:
        answer, urls = await service.consult(question, case_context=case_context, language=language)
    except Exception:
        if not await consultation_request_is_current(state, consultation_request_id):
            LOGGER.info(
                "STALE_CONSULTATION_SUPPRESSED request_id=%s user=%s stage=exception",
                consultation_request_id,
                message.from_user.id if message.from_user else None,
            )
            return _STALE
        LOGGER.exception("CONSULTATION_LIMIT consultation failed user=%s", message.from_user.id if message.from_user else None)
        return _FAILED

    if not await consultation_request_is_current(state, consultation_request_id):
        LOGGER.info(
            "STALE_CONSULTATION_SUPPRESSED request_id=%s user=%s stage=after_generation",
            consultation_request_id,
            message.from_user.id if message.from_user else None,
        )
        return _STALE

    if not await _remember_consultation_result(state, answer, urls, consultation_request_id):
        LOGGER.info(
            "STALE_CONSULTATION_SUPPRESSED request_id=%s user=%s stage=state_write",
            consultation_request_id,
            message.from_user.id if message.from_user else None,
        )
        return _STALE

    sources = ""
    if urls:
        source_title = "Ресми дереккөздер:" if language == "kk" else "Официальные источники:"
        sources = "\n\n" + source_title + "\n" + "\n".join(f"• {url}" for url in urls[:5])
    for part in base_bot._split(answer + sources):
        async with document_request_lock(state):
            refreshed = await state.get_data()
            if str(refreshed.get("consultation_request_id") or "") != consultation_request_id:
                LOGGER.info(
                    "STALE_CONSULTATION_SUPPRESSED request_id=%s user=%s stage=delivery",
                    consultation_request_id,
                    message.from_user.id if message.from_user else None,
                )
                return _STALE
            await message.answer(part, disable_web_page_preview=True, reply_markup=base_bot.MENU)
    return _DELIVERED


async def _deliver_paid_order(message: Message, state: FSMContext, order: ConsultationOrder) -> None:
    if order.status != "paid":
        await message.answer("Этот платёжный запрос уже обработан или ещё не подтверждён.")
        return

    facts_data = await state.get_data()
    facts = list(facts_data.get("facts", []) or [])
    if order.question not in facts[-3:]:
        facts.append(order.question)
    await state.update_data(facts=facts[-20:], mode="main")

    delivery = await _send_consultation_answer(
        message,
        state,
        question=order.question,
        case_context=order.case_context,
        language=order.language,
    )
    if delivery == _FAILED:
        text = (
            "⚠️ Оплата уже подтверждена через Kaspi ОФД, но юридический AI временно не ответил. Повторно платить не нужно."
            if order.language != "kk"
            else "⚠️ Төлем Kaspi ОФД арқылы расталды, бірақ заңдық AI уақытша жауап бермеді. Қайта төлеудің қажеті жоқ."
        )
        await message.answer(text, reply_markup=retry_markup(get_settings(), order.user_id, order.id, order.language))
        return
    if delivery == _STALE:
        latest = await get_consultation_order(order.id, order.user_id)
        if latest is None or latest.status != "paid":
            return
        text = (
            "ℹ️ Пока готовился ответ, вы начали новый запрос. Старый ответ не отправлен. Оплата сохранена — эту консультацию можно повторить без новой оплаты."
            if order.language != "kk"
            else "ℹ️ Жауап дайындалып жатқанда сіз жаңа сұрау бастадыңыз. Ескі жауап жіберілмеді. Төлем сақталды — кеңесті қайта төлемей қайталауға болады."
        )
        await message.answer(text, reply_markup=retry_markup(get_settings(), order.user_id, order.id, order.language))
        return

    if not await mark_consultation_consumed(order.id, order.user_id):
        LOGGER.warning("CONSULTATION_PAID_MARK_CONSUMED_RACE order=%s user=%s", order.id, order.user_id)


async def _verify_consultation_fiscal_url(message: Message, state: FSMContext, receipt_url: str) -> None:
    settings = get_settings()
    user_id = message.from_user.id if message.from_user else None
    if user_id is None:
        return

    data = await state.get_data()
    try:
        order_id = int(data.get("consultation_payment_order_id"))
    except (TypeError, ValueError):
        await state.update_data(mode="main")
        await message.answer("Платёжная сессия устарела. Нажмите «✅ Я оплатил» под карточкой оплаты ещё раз.")
        return

    order = await get_consultation_order(order_id, user_id)
    if order is None or order.status != "pending":
        await state.update_data(mode="main")
        await message.answer("Этот платёжный запрос уже обработан или устарел.")
        return

    offer_time = str(data.get("consultation_payment_offer_time") or "").strip()
    expected_bin = settings.payment_seller_bin
    expected_recipient = settings.kaspi_payment_recipient.strip()
    if not offer_time or not (expected_bin or expected_recipient):
        LOGGER.critical(
            "CONSULTATION_OFD_CONTEXT_MISSING user=%s order=%s offer_time=%s bin=%s recipient=%s",
            user_id,
            order_id,
            bool(offer_time),
            bool(expected_bin),
            bool(expected_recipient),
        )
        await message.answer("⚠️ Проверка Kaspi ОФД временно недоступна. Консультация остаётся заблокирована; повторно платить не нужно.")
        return

    try:
        receipt = await fetch_kaspi_ofd_receipt(receipt_url)
    except KaspiOFDVerificationError as exc:
        LOGGER.warning("CONSULTATION_OFD_URL_REJECTED user=%s order=%s reason=%s", user_id, order_id, str(exc)[:160])
        await message.answer(f"❌ Фискальный чек не подтверждён: {exc}.\n\n{_fiscal_qr_instruction(order.language)}")
        return
    except Exception:
        LOGGER.exception("CONSULTATION_OFD_FETCH_FAILED user=%s order=%s", user_id, order_id)
        await message.answer("⚠️ Kaspi ОФД сейчас недоступен. Повторно платить не нужно — отправьте ту же QR-ссылку позже.")
        return

    issues = fiscal_receipt_issues(
        receipt,
        order.amount_kzt,
        expected_recipient=expected_recipient,
        expected_bin=expected_bin,
        offered_at=offer_time,
    )
    if issues:
        LOGGER.warning("CONSULTATION_OFD_REJECTED user=%s order=%s issues=%s", user_id, order_id, issues[:6])
        await message.answer(
            "❌ Фискальный чек не прошёл проверку Kaspi ОФД:\n• "
            + "\n• ".join(issues[:6])
            + "\n\nКонсультация не разблокирована."
        )
        return

    try:
        accepted = await accept_consultation_receipt(
            order_id=order.id,
            user_id=user_id,
            receipt_hash=receipt.receipt_fingerprint,
            transaction_id=receipt.transaction_id,
        )
    except Exception:
        LOGGER.exception("CONSULTATION_OFD_REPLAY_GUARD_FAILED user=%s order=%s", user_id, order_id)
        await message.answer("⚠️ Не удалось безопасно закрепить фискальный чек. Консультация остаётся заблокирована; повторно платить не нужно.")
        return
    if not accepted:
        await message.answer("❌ Этот фискальный чек уже использовался либо платёжный запрос уже обработан.")
        return

    LOGGER.info(
        "CONSULTATION_KASPI_OFD_VERIFIED user=%s order=%s fiscal_transaction=%s amount=%s seller_bin=%s",
        user_id,
        order_id,
        receipt.transaction_id[:120],
        receipt.amount_kzt,
        receipt.seller_bin,
    )
    await state.update_data(mode="main")
    await message.answer("✅ Kaspi ОФД подтвердил фискальный чек. Выполняю оплаченную консультацию…")
    paid_order = await get_consultation_order(order.id, user_id)
    if paid_order is not None:
        await _deliver_paid_order(message, state, paid_order)


@router.callback_query(F.data.startswith("cp:proof:"))
async def consultation_payment_proof_requested(callback: CallbackQuery, state: FSMContext) -> None:
    settings = get_settings()
    parsed = _parse_callback(callback.data or "", "proof")
    user_id = callback.from_user.id if callback.from_user else None
    if not settings.consultation_limit_enabled or parsed is None or user_id is None:
        await callback.answer("Некорректный запрос.", show_alert=True)
        return

    order_id, signature = parsed
    if not verify_consultation_signature(settings, signature, user_id, order_id):
        await callback.answer("Некорректная или устаревшая ссылка.", show_alert=True)
        return
    order = await get_consultation_order(order_id, user_id)
    if order is None or order.status != "pending":
        await callback.answer("Этот платёжный запрос уже обработан.", show_alert=True)
        return

    offer_date = getattr(callback.message, "date", None) if callback.message else None
    offer_time = offer_date.isoformat() if offer_date is not None else ""
    await state.update_data(
        mode="consultation_payment_receipt",
        consultation_payment_order_id=order_id,
        consultation_payment_offer_time=offer_time,
    )
    await callback.answer()
    if callback.message:
        await callback.message.answer(_fiscal_qr_instruction(order.language))


@router.message(ConsultationReceiptTextFilter())
async def consultation_receipt_text(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    language = "ru"
    try:
        order_id = int(data.get("consultation_payment_order_id"))
        order = await get_consultation_order(order_id, message.from_user.id if message.from_user else 0)
        if order is not None:
            language = order.language
    except (TypeError, ValueError):
        pass

    text = str(message.text or "").strip()
    if "receipt.kaspi.kz" not in text.casefold():
        await message.answer(_fiscal_qr_instruction(language))
        return
    await _verify_consultation_fiscal_url(message, state, text)


@router.message(ConsultationReceiptFilter())
async def consultation_receipt_received(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    language = "ru"
    try:
        order_id = int(data.get("consultation_payment_order_id"))
        order = await get_consultation_order(order_id, message.from_user.id if message.from_user else 0)
        if order is not None:
            language = order.language
    except (TypeError, ValueError):
        pass
    await message.answer(_fiscal_qr_instruction(language))


@router.callback_query(F.data.startswith("cp:retry:"))
async def retry_paid_consultation(callback: CallbackQuery, state: FSMContext) -> None:
    settings = get_settings()
    parsed = _parse_callback(callback.data or "", "retry")
    user_id = callback.from_user.id if callback.from_user else None
    if parsed is None or user_id is None:
        await callback.answer("Некорректный запрос.", show_alert=True)
        return
    order_id, signature = parsed
    if not verify_consultation_signature(settings, signature, user_id, order_id):
        await callback.answer("Некорректная ссылка.", show_alert=True)
        return
    order = await get_consultation_order(order_id, user_id)
    if order is None or order.status != "paid":
        await callback.answer("Эта консультация уже обработана.", show_alert=True)
        return
    await callback.answer()
    if callback.message:
        await _deliver_paid_order(callback.message, state, order)


@router.message(LimitedConsultationFilter())
async def limited_consultation(message: Message, state: FSMContext) -> None:
    settings = get_settings()
    user_id = message.from_user.id if message.from_user else None
    if user_id is None or not message.text:
        return

    consultation_request_id = await start_new_consultation_request(state)
    language = await base_bot._language(state)
    case_context_before_question = await base_bot._case_context(state)
    used = await reserve_free_consultation(user_id, settings.free_consultations_per_day)

    if used is None:
        order = await create_consultation_order(
            user_id=user_id,
            chat_id=message.chat.id,
            question=message.text,
            case_context=case_context_before_question,
            language=language,
            amount_kzt=settings.consultation_price_kzt,
        )
        await state.update_data(mode="main")
        await message.answer(
            _consultation_payment_text_ofd(language, settings.free_consultations_per_day, settings.consultation_price_kzt),
            reply_markup=consultation_payment_markup(settings, user_id, order.id, language),
        )
        return

    facts_data = await state.get_data()
    facts = list(facts_data.get("facts", []) or [])
    facts.append(message.text)
    await state.update_data(facts=facts[-20:], mode="main")
    case_context = await base_bot._case_context(state)

    delivery = await _send_consultation_answer(
        message,
        state,
        question=message.text,
        case_context=case_context,
        language=language,
        consultation_request_id=consultation_request_id,
    )
    if delivery == _FAILED:
        await release_free_consultation(user_id)
        await message.answer("Не удалось выполнить юридический поиск. Бесплатный запрос не списан — попробуйте ещё раз.", reply_markup=base_bot.MENU)
        return
    if delivery == _STALE:
        await release_free_consultation(user_id)
        return

    remaining = max(settings.free_consultations_per_day - used, 0)
    if remaining <= 2:
        text = (
            f"🆓 Бесплатных консультаций сегодня осталось: {remaining}."
            if language != "kk"
            else f"🆓 Бүгін тегін кеңес қалды: {remaining}."
        )
        await message.answer(text, reply_markup=base_bot.MENU)
