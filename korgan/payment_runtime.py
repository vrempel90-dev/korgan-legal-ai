from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import BaseFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from korgan.admin import is_admin
from korgan.config import get_settings
from korgan.document_receipt_replay_guard import reserve_verified_document_receipt
from korgan.kaspi_ofd import (
    KaspiOFDVerificationError,
    fetch_kaspi_ofd_receipt,
    fiscal_receipt_issues,
)
from korgan.localized_transport import _document_caption_with_review, _document_review_markup
from korgan.payment import verify_admin_action, verify_user_payment
from korgan.payment_release_guard import can_release_paid_document

LOGGER = logging.getLogger(__name__)
router = Router(name="korgan-payment-runtime")


class PaymentReceiptFilter(BaseFilter):
    async def __call__(self, message: Message, state: FSMContext) -> bool:
        data = await state.get_data()
        return data.get("mode") == "payment_receipt" and bool(message.photo or message.document)


class PaymentReceiptTextFilter(BaseFilter):
    async def __call__(self, message: Message, state: FSMContext) -> bool:
        data = await state.get_data()
        return data.get("mode") == "payment_receipt" and bool(message.text)


def _parse_user_callback(data: str) -> tuple[int, str, str, str] | None:
    parts = data.split(":")
    if len(parts) != 6 or parts[:2] != ["pay", "proof"]:
        return None
    try:
        return int(parts[2]), parts[3], parts[4], parts[5]
    except ValueError:
        return None


def _parse_admin_callback(data: str) -> tuple[str, int, int, str, str, str] | None:
    """Compatibility parser for admin cards created by older deployments."""
    parts = data.split(":")
    if len(parts) != 7 or parts[0] != "pay" or parts[1] not in {"ok", "no"}:
        return None
    try:
        return parts[1], int(parts[2]), int(parts[3]), parts[4], parts[5], parts[6]
    except ValueError:
        return None


def _fiscal_qr_instruction(language: str) -> str:
    if language == "kk":
        return (
            "🔎 Фискалдық чектегі QR-кодты телефон камерасымен сканерлеңіз. "
            "Ашылған receipt.kaspi.kz сілтемесін осы чатқа жіберіңіз.\n\n"
            "Фото, скриншот немесе PDF төлемді растамайды: KORGAN төлемді тікелей Kaspi ОФД деректері бойынша тексереді."
        )
    return (
        "🔎 Отсканируйте QR-код именно на фискальном чеке камерой телефона. "
        "Отправьте сюда открывшуюся ссылку receipt.kaspi.kz.\n\n"
        "Фото, скриншот или PDF не подтверждают оплату: KORGAN проверяет платёж напрямую по данным Kaspi ОФД."
    )


@router.message(F.text.in_({"💰 Цены", "💰 Бағалар"}))
async def payment_prices(message: Message, state: FSMContext) -> None:
    settings = get_settings()
    await state.update_data(mode="main")
    language = str((await state.get_data()).get("language", "ru"))
    amount = f"{settings.document_price_kzt:,}".replace(",", " ")
    if language == "kk":
        text = (
            "💰 KORGAN акциялық бағасы\n\n"
            f"🔥 Кез келген заңдық құжат — {amount} ₸\n\n"
            "• Талап қою арызы\n"
            "• Сотқа дейінгі талап\n"
            "• Талапқа пікір\n"
            "• Шарт\n\n"
            "💳 Төлем Kaspi арқылы жүргізіледі. Word-файл фискалдық чектің QR-сілтемесі Kaspi ОФД арқылы тексерілгеннен кейін ғана дайындалады/беріледі.\n\n"
            "👨‍⚖️ Дайын құжатты кәсіби заңгердің тексеруі — бөлек ақылы қызмет."
        )
    else:
        text = (
            "💰 Акционная цена KORGAN\n\n"
            f"🔥 Любой юридический документ — {amount} ₸\n\n"
            "• Исковое заявление\n"
            "• Досудебная претензия\n"
            "• Отзыв на иск\n"
            "• Договор\n\n"
            "💳 Оплата через Kaspi. Word-файл готовится/выдаётся только после проверки QR фискального чека через Kaspi ОФД.\n\n"
            "👨‍⚖️ Проверка готового документа профессиональным юристом — отдельная платная услуга."
        )
    await message.answer(text)


@router.callback_query(F.data.startswith("pay:proof:"))
async def payment_proof_requested(callback: CallbackQuery, state: FSMContext) -> None:
    parsed = _parse_user_callback(callback.data or "")
    settings = get_settings()
    if parsed is None or callback.from_user is None:
        await callback.answer("Некорректный запрос.", show_alert=True)
        return
    transaction_id, kind, language, signature = parsed
    user_id = callback.from_user.id
    if not verify_user_payment(settings, signature, user_id, transaction_id, kind, language):
        LOGGER.warning("PAYMENT_USER_SIGNATURE_REJECTED user=%s", user_id)
        await callback.answer("Запрос устарел. Сформируйте документ заново.", show_alert=True)
        return

    offer_date = getattr(callback.message, "date", None) if callback.message else None
    offer_time = offer_date.isoformat() if offer_date is not None else ""
    await state.update_data(
        mode="payment_receipt",
        payment_admin_doc_message_id=transaction_id,
        payment_kind=kind,
        payment_language=language,
        payment_signature=signature,
        payment_offer_time=offer_time,
    )
    await callback.answer()
    if callback.message:
        await callback.message.answer(_fiscal_qr_instruction(language))


async def _verify_and_release_fiscal_url(message: Message, state: FSMContext, receipt_url: str) -> None:
    settings = get_settings()
    data = await state.get_data()
    user_id = message.from_user.id if message.from_user else None
    if user_id is None:
        return

    try:
        payment_transaction_id = int(data.get("payment_admin_doc_message_id"))
    except (TypeError, ValueError):
        await state.update_data(mode="main")
        await message.answer("Платёжная сессия устарела. Нажмите «✅ Я оплатил» под карточкой оплаты ещё раз.")
        return

    kind = str(data.get("payment_kind") or "")
    language = str(data.get("payment_language") or "ru")
    signature = str(data.get("payment_signature") or "")
    if not verify_user_payment(settings, signature, user_id, payment_transaction_id, kind, language):
        await state.update_data(mode="main")
        await message.answer("Платёжная сессия устарела. Нажмите «✅ Я оплатил» ещё раз.")
        return

    offer_time = str(data.get("payment_offer_time") or "").strip()
    expected_recipient = settings.kaspi_payment_recipient.strip()
    expected_bin = settings.kaspi_payment_bin.strip()
    if not offer_time or not (expected_bin or expected_recipient):
        LOGGER.critical(
            "PAYMENT_OFD_CONTEXT_MISSING user=%s kind=%s offer_time=%s recipient=%s bin=%s",
            user_id,
            kind,
            bool(offer_time),
            bool(expected_recipient),
            bool(expected_bin),
        )
        await message.answer(
            "⚠️ Проверка Kaspi ОФД временно недоступна из-за конфигурации. Документ остаётся заблокирован. Повторно платить не нужно."
            if language != "kk"
            else
            "⚠️ Kaspi ОФД тексеруі баптауға байланысты уақытша қолжетімсіз. Құжат бұғатталған күйде қалады. Қайта төлеу қажет емес."
        )
        return

    try:
        receipt = await fetch_kaspi_ofd_receipt(receipt_url)
    except KaspiOFDVerificationError as exc:
        LOGGER.warning("PAYMENT_OFD_URL_REJECTED user=%s kind=%s reason=%s", user_id, kind, str(exc)[:160])
        await message.answer(
            f"❌ Фискальный чек не подтверждён: {exc}.\n\n{_fiscal_qr_instruction(language)}"
            if language != "kk"
            else f"❌ Фискалдық чек расталмады: {exc}.\n\n{_fiscal_qr_instruction(language)}"
        )
        return
    except Exception:
        LOGGER.exception("PAYMENT_OFD_FETCH_FAILED user=%s kind=%s", user_id, kind)
        await message.answer(
            "⚠️ Kaspi ОФД сейчас недоступен. Документ остаётся заблокирован. Повторно платить не нужно — отправьте ту же QR-ссылку позже."
            if language != "kk"
            else "⚠️ Kaspi ОФД қазір қолжетімсіз. Құжат бұғатталған күйде қалады. Қайта төлеу қажет емес — сол QR-сілтемені кейін жіберіңіз."
        )
        return

    issues = fiscal_receipt_issues(
        receipt,
        settings.document_price_kzt,
        expected_recipient=expected_recipient,
        expected_bin=expected_bin,
        offered_at=offer_time,
    )
    if issues:
        LOGGER.warning("PAYMENT_OFD_REJECTED user=%s kind=%s issues=%s", user_id, kind, issues[:6])
        await message.answer(
            ("❌ Фискальный чек не прошёл проверку Kaspi ОФД:\n• " + "\n• ".join(issues[:6]) + "\n\nДокумент не запущен и не выдан.")
            if language != "kk"
            else ("❌ Фискалдық чек Kaspi ОФД тексеруінен өтпеді:\n• " + "\n• ".join(issues[:6]) + "\n\nҚұжат іске қосылған жоқ және берілген жоқ.")
        )
        return

    release_guard = can_release_paid_document(
        kind=kind,
        receipt_submitted=True,
        receipt_precheck_passed=True,
        ofd_verified=True,
    )
    if not release_guard.allowed:
        LOGGER.critical("PAYMENT_OFD_RELEASE_GUARD_BLOCKED user=%s kind=%s reason=%s", user_id, kind, release_guard.reason)
        await message.answer("Документ не выдан: защищённая проверка оплаты не завершена.")
        return

    request_id = str(data.get("prepayment_request_id") or data.get("request_id") or f"legacy:{payment_transaction_id}")
    try:
        reserved = await reserve_verified_document_receipt(
            receipt_hash=receipt.receipt_fingerprint,
            transaction_id=receipt.transaction_id,
            user_id=user_id,
            request_id=request_id,
            document_kind=kind,
        )
    except Exception:
        LOGGER.exception(
            "PAYMENT_OFD_REPLAY_GUARD_FAILED user=%s kind=%s transaction=%s",
            user_id,
            kind,
            payment_transaction_id,
        )
        await message.answer(
            "⚠️ Не удалось безопасно проверить уникальность фискального чека. Документ остаётся заблокирован. Повторно платить не нужно — отправьте эту же QR-ссылку позже."
            if language != "kk"
            else "⚠️ Фискалдық чектің бірегейлігін қауіпсіз тексеру мүмкін болмады. Құжат бұғатталған күйде қалады. Қайта төлеу қажет емес — сол QR-сілтемені кейін жіберіңіз."
        )
        return
    if not reserved:
        LOGGER.warning(
            "PAYMENT_OFD_REPLAY_BLOCKED user=%s kind=%s transaction=%s receipt_id=%s",
            user_id,
            kind,
            payment_transaction_id,
            receipt.transaction_id[:120],
        )
        await message.answer(
            "❌ Этот фискальный чек уже использовался для другой выдачи. Документ не запущен."
            if language != "kk"
            else "❌ Бұл фискалдық чек басқа құжат үшін бұрын қолданылған. Құжат іске қосылған жоқ."
        )
        return

    LOGGER.info(
        "PAYMENT_KASPI_OFD_VERIFIED user=%s kind=%s payment_transaction=%s fiscal_transaction=%s amount=%s seller_bin=%s rnm=%s fp=%s",
        user_id,
        kind,
        payment_transaction_id,
        receipt.transaction_id[:120],
        receipt.amount_kzt,
        receipt.seller_bin,
        receipt.rnm[:80],
        receipt.fp[:80],
    )

    if payment_transaction_id < 0:
        # Function name is retained for backward compatibility with the existing
        # paid-generation state machine; no AI payment verification is used here.
        from korgan.prepayment_runtime import run_ai_verified_prepayment_generation

        started = await run_ai_verified_prepayment_generation(
            message=message,
            state=state,
            user_id=user_id,
            transaction_id=payment_transaction_id,
            kind=kind,
            language=language,
        )
        if not started:
            await state.update_data(mode="payment_receipt")
            await message.answer(
                "⚠️ Фискальный чек уже закреплён за этой заявкой, но документ не удалось запустить. Повторно платить не нужно — отправьте ту же QR-ссылку ещё раз."
                if language != "kk"
                else "⚠️ Фискалдық чек осы өтінімге бекітілді, бірақ құжатты іске қосу мүмкін болмады. Қайта төлеу қажет емес — сол QR-сілтемені қайта жіберіңіз."
            )
        return

    storage_admin_id = next((admin_id for admin_id in sorted(settings.admin_ids) if admin_id != user_id), None)
    if storage_admin_id is None:
        LOGGER.error("PAYMENT_LEGACY_STORAGE_MISSING user=%s kind=%s", user_id, kind)
        await state.update_data(mode="payment_receipt")
        await message.answer("Оплата проверена через Kaspi ОФД, но старый сохранённый документ недоступен. Обратитесь в техподдержку; повторно платить не нужно.")
        return
    try:
        await message.bot.copy_message(
            chat_id=user_id,
            from_chat_id=storage_admin_id,
            message_id=payment_transaction_id,
            caption=_document_caption_with_review(kind, language),
            reply_markup=_document_review_markup(kind, language),
        )
    except Exception:
        LOGGER.exception("PAYMENT_LEGACY_OFD_RELEASE_FAILED user=%s doc_msg=%s", user_id, payment_transaction_id)
        await state.update_data(mode="payment_receipt")
        await message.answer("Оплата проверена через Kaspi ОФД, но старый документ не удалось выдать. Повторно платить не нужно; отправьте ту же QR-ссылку ещё раз или обратитесь в техподдержку.")
        return

    await state.update_data(mode="main")
    LOGGER.info("PAYMENT_KASPI_OFD_LEGACY_RELEASE user=%s kind=%s transaction=%s", user_id, kind, payment_transaction_id)
    await message.answer(
        "✅ Kaspi ОФД подтвердил фискальный чек. Оплата принята, Word-файл выдан выше."
        if language != "kk"
        else "✅ Kaspi ОФД фискалдық чекті растады. Төлем қабылданды, Word-файл жоғарыда берілді."
    )


@router.message(PaymentReceiptTextFilter())
async def payment_receipt_text(message: Message, state: FSMContext) -> None:
    text = str(message.text or "").strip()
    if "receipt.kaspi.kz" not in text.casefold():
        language = str((await state.get_data()).get("payment_language", "ru"))
        await message.answer(_fiscal_qr_instruction(language))
        return
    await _verify_and_release_fiscal_url(message, state, text)


@router.message(PaymentReceiptFilter())
async def payment_receipt_received(message: Message, state: FSMContext) -> None:
    """Images/PDFs never decide payment; the fiscal QR URL is authoritative."""
    language = str((await state.get_data()).get("payment_language", "ru"))
    await message.answer(_fiscal_qr_instruction(language))


@router.callback_query(F.data.startswith("pay:ok:") | F.data.startswith("pay:no:"))
async def admin_payment_decision(callback: CallbackQuery) -> None:
    """Legacy recovery for admin cards sent before automatic OFD verification."""
    parsed = _parse_admin_callback(callback.data or "")
    settings = get_settings()
    admin_id = callback.from_user.id if callback.from_user else None
    if parsed is None or not is_admin(admin_id, settings):
        await callback.answer("Недостаточно прав.", show_alert=True)
        return

    action, user_id, admin_doc_message_id, kind, language, signature = parsed
    if not verify_admin_action(settings, signature, user_id, admin_doc_message_id, kind, language):
        LOGGER.warning("PAYMENT_ADMIN_SIGNATURE_REJECTED admin=%s user=%s", admin_id, user_id)
        await callback.answer("Некорректная или устаревшая заявка.", show_alert=True)
        return
    if callback.message is None:
        await callback.answer("Сообщение недоступно.", show_alert=True)
        return

    current_text = callback.message.text or ""
    if "ОПЛАТА ПОДТВЕРЖДЕНА" in current_text or "ОПЛАТА ОТКЛОНЕНА" in current_text:
        await callback.answer("Решение уже принято.", show_alert=True)
        return

    if action == "no":
        await callback.answer("Оплата отклонена.")
        await callback.message.edit_text(current_text + "\n\n❌ ОПЛАТА ОТКЛОНЕНА", reply_markup=None)
        await callback.bot.send_message(user_id, "❌ Старый платёж отклонён. Документ не выдан.")
        return

    release_guard = can_release_paid_document(
        kind=kind,
        receipt_submitted=True,
        receipt_precheck_passed=True,
        admin_confirmed=True,
    )
    if not release_guard.allowed:
        await callback.answer("Документ остаётся заблокирован.", show_alert=True)
        return

    try:
        await callback.bot.copy_message(
            chat_id=user_id,
            from_chat_id=callback.message.chat.id,
            message_id=admin_doc_message_id,
            caption=_document_caption_with_review(kind, language),
            reply_markup=_document_review_markup(kind, language),
        )
    except Exception:
        LOGGER.exception("PAYMENT_LEGACY_DOCUMENT_RELEASE_FAILED user=%s doc_msg=%s", user_id, admin_doc_message_id)
        await callback.answer("Не удалось выдать старый документ. Повторите.", show_alert=True)
        return

    await callback.answer("Старый платёж подтверждён, документ выдан.")
    await callback.message.edit_text(current_text + "\n\n✅ LEGACY ОПЛАТА ПОДТВЕРЖДЕНА — документ выдан.", reply_markup=None)
