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
    consultation_payment_text,
    create_consultation_order,
    get_consultation_order,
    mark_consultation_consumed,
    receipt_fingerprint,
    release_free_consultation,
    reserve_free_consultation,
    retry_markup,
    strict_consultation_receipt_issues,
    verify_consultation_signature,
)
from korgan.legal_corpus import extract_cited_articles
from korgan.payment import ReceiptAnalyzer
from korgan.payment_runtime import _receipt_bytes
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


async def _remember_consultation_result(
    state: FSMContext,
    answer: str,
    urls: list[str],
    consultation_request_id: str,
) -> bool:
    """Atomically persist citation hints only for the still-active consultation."""
    cited = extract_cited_articles(answer) if urls else []
    async with document_request_lock(state):
        refreshed = dict(await state.get_data())
        if str(refreshed.get("consultation_request_id") or "") != consultation_request_id:
            return False
        if not cited:
            return True
        previous = list(refreshed.get("consulted_articles", []) or [])
        for item in cited:
            if item not in previous:
                previous.append(item)
        refreshed["consulted_articles"] = previous[-20:]
        await state.set_data(refreshed)
        return True


async def _send_consultation_answer(
    message: Message,
    state: FSMContext,
    *,
    question: str,
    case_context: str,
    language: str,
) -> str:
    """Generate and deliver only while this consultation still owns the session.

    Telegram updates run concurrently. A newer consultation or any new document
    request invalidates this token. We cannot cancel an OpenAI call already in
    flight, but we fail closed before its result mutates state or reaches the
    client.
    """
    service = base_bot.service
    if service is None:
        await message.answer("Юридический AI-сервис временно недоступен.")
        return _FAILED

    consultation_request_id = await start_new_consultation_request(state)
    await message.bot.send_chat_action(message.chat.id, "typing")
    try:
        answer, urls = await service.consult(question, case_context=case_context, language=language)
    except Exception:
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
        # Hold the same per-session lock across the final ownership check and
        # each client send. A new document request either commits first and
        # suppresses this message, or waits until this already-current message
        # is sent and then becomes the new owner.
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
            "⚠️ Чек уже принят, но юридический AI временно не ответил. Деньги повторно платить не нужно."
            if order.language != "kk"
            else "⚠️ Чек қабылданды, бірақ заңдық AI уақытша жауап бермеді. Қайта төлеудің қажеті жоқ."
        )
        await message.answer(text, reply_markup=retry_markup(get_settings(), order.user_id, order.id, order.language))
        return
    if delivery == _STALE:
        text = (
            "ℹ️ Пока готовился ответ, вы начали новый запрос. Старый ответ не отправлен. Оплата сохранена — эту консультацию можно повторить без новой оплаты."
            if order.language != "kk"
            else "ℹ️ Жауап дайындалып жатқанда сіз жаңа сұрау бастадыңыз. Ескі жауап жіберілмеді. Төлем сақталды — кеңесті қайта төлемей қайталауға болады."
        )
        await message.answer(text, reply_markup=retry_markup(get_settings(), order.user_id, order.id, order.language))
        return

    if not await mark_consultation_consumed(order.id, order.user_id):
        LOGGER.warning("CONSULTATION_PAID_MARK_CONSUMED_RACE order=%s user=%s", order.id, order.user_id)


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

    await state.update_data(mode="consultation_payment_receipt", consultation_payment_order_id=order_id)
    await callback.answer()
    if callback.message:
        text = (
            "📎 Пришлите полный чек Kaspi фото или PDF. Должны быть видны сумма 1 000 ₸, дата/время, получатель и успешный статус оплаты."
            if order.language != "kk"
            else "📎 Kaspi толық чегін фото немесе PDF түрінде жіберіңіз. 1 000 ₸ сомасы, күн/уақыт, алушы және сәтті төлем мәртебесі көрінуі керек."
        )
        await callback.message.answer(text)


@router.message(ConsultationReceiptTextFilter())
async def consultation_receipt_text(message: Message) -> None:
    await message.answer("📎 Пришлите сам чек как фото, JPG/PNG/WEBP или PDF.")


@router.message(ConsultationReceiptFilter())
async def consultation_receipt_received(message: Message, state: FSMContext) -> None:
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

    payload = await _receipt_bytes(message)
    if payload is None:
        await message.answer("Не удалось прочитать файл. Пришлите полный чек как фото, JPG/PNG/WEBP или PDF.")
        return
    raw, filename, mime = payload

    await message.answer("🔎 Проверяю чек: сумму, статус оплаты, реквизиты и признаки редактирования…")
    try:
        check = await ReceiptAnalyzer(settings).analyze(raw, filename, mime)
    except Exception:
        LOGGER.exception("CONSULTATION_RECEIPT_AI_FAILED user=%s order=%s", user_id, order_id)
        await message.answer("Не удалось проверить чек. Консультация не разблокирована — попробуйте отправить чек ещё раз.")
        return

    issues = strict_consultation_receipt_issues(check, order.amount_kzt)
    if issues:
        await message.answer(
            "❌ Чек не прошёл автоматическую проверку:\n• "
            + "\n• ".join(issues[:6])
            + "\n\nКонсультация не разблокирована. Пришлите полный корректный чек."
        )
        return

    accepted = await accept_consultation_receipt(
        order_id=order.id,
        user_id=user_id,
        receipt_hash=receipt_fingerprint(raw),
        transaction_id=check.receipt_or_transaction_id,
    )
    if not accepted:
        await message.answer("❌ Этот чек или номер операции уже использовался либо платёжный запрос уже обработан.")
        return

    await state.update_data(mode="main")
    await message.answer("✅ Чек прошёл автоматическую проверку. Выполняю оплаченную консультацию…")
    paid_order = await get_consultation_order(order.id, user_id)
    if paid_order is not None:
        await _deliver_paid_order(message, state, paid_order)


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
            consultation_payment_text(language, settings.free_consultations_per_day, settings.consultation_price_kzt),
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
