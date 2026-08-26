from __future__ import annotations

import io
import logging

from aiogram import F, Router
from aiogram.filters import BaseFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from korgan.admin import is_admin
from korgan.config import get_settings
from korgan.localized_transport import _document_caption_with_review, _document_review_markup
from korgan.payment import (
    ReceiptAnalyzer,
    receipt_hard_issues,
    verify_admin_action,
    verify_user_payment,
)
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


async def _receipt_bytes(message: Message) -> tuple[bytes, str, str] | None:
    if message.photo:
        item = message.photo[-1]
        file_id = item.file_id
        filename = "kaspi_receipt.jpg"
        mime = "image/jpeg"
    elif message.document:
        doc = message.document
        filename = doc.file_name or "kaspi_receipt"
        mime = doc.mime_type or "application/octet-stream"
        suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
        if mime not in {"application/pdf", "image/jpeg", "image/png", "image/webp"} and suffix not in {"pdf", "jpg", "jpeg", "png", "webp"}:
            return None
        file_id = doc.file_id
    else:
        return None

    tg_file = await message.bot.get_file(file_id)
    if not tg_file.file_path:
        return None
    output = io.BytesIO()
    await message.bot.download_file(tg_file.file_path, destination=output)
    return output.getvalue(), filename, mime


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
            "💳 Төлем Kaspi арқылы жүргізіледі. Word-файл KORGAN AI чекті тексергеннен кейін ғана дайындалып/беріледі.\n\n"
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
            "💳 Оплата через Kaspi. Word-файл готовится/выдаётся только после автоматической проверки чека KORGAN AI.\n\n"
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
    admin_doc_message_id, kind, language, signature = parsed
    user_id = callback.from_user.id
    if not verify_user_payment(settings, signature, user_id, admin_doc_message_id, kind, language):
        LOGGER.warning("PAYMENT_USER_SIGNATURE_REJECTED user=%s", user_id)
        await callback.answer("Запрос устарел. Сформируйте документ заново.", show_alert=True)
        return

    await state.update_data(
        mode="payment_receipt",
        payment_admin_doc_message_id=admin_doc_message_id,
        payment_kind=kind,
        payment_language=language,
        payment_signature=signature,
    )
    await callback.answer()
    if callback.message:
        text = (
            "📎 Төлем чегін толық түрде фото немесе PDF ретінде жіберіңіз. Сома, күн/уақыт, операция нөмірі және төлем мәртебесі көрінуі керек. AI тексеруі сәтті болса, құжат автоматты түрде іске қосылады."
            if language == "kk"
            else
            "📎 Пришлите полный чек оплаты фото или PDF. Должны быть видны сумма, дата/время, номер операции и успешный статус платежа. Если AI-проверка пройдена, документ запустится автоматически."
        )
        await callback.message.answer(text)


@router.message(PaymentReceiptTextFilter())
async def payment_receipt_text(message: Message, state: FSMContext) -> None:
    language = str((await state.get_data()).get("payment_language", "ru"))
    await message.answer(
        "📎 Чектің өзін фото, JPG/PNG/WEBP немесе PDF түрінде жіберіңіз."
        if language == "kk"
        else
        "📎 Пришлите сам чек как фото, JPG/PNG/WEBP или PDF."
    )


@router.message(PaymentReceiptFilter())
async def payment_receipt_received(message: Message, state: FSMContext) -> None:
    """AI-verifies a receipt and immediately releases/starts the paid document."""
    settings = get_settings()
    data = await state.get_data()
    user_id = message.from_user.id if message.from_user else None
    if user_id is None:
        return

    try:
        transaction_id = int(data.get("payment_admin_doc_message_id"))
    except (TypeError, ValueError):
        await state.update_data(mode="main")
        await message.answer("Платёжная сессия устарела. Нажмите «✅ Я оплатил» под карточкой оплаты ещё раз.")
        return
    kind = str(data.get("payment_kind") or "")
    language = str(data.get("payment_language") or "ru")
    signature = str(data.get("payment_signature") or "")
    if not verify_user_payment(settings, signature, user_id, transaction_id, kind, language):
        await state.update_data(mode="main")
        await message.answer("Платёжная сессия устарела. Нажмите «✅ Я оплатил» ещё раз.")
        return

    payload = await _receipt_bytes(message)
    if payload is None:
        await message.answer("Не удалось прочитать файл. Пришлите полный чек как фото, JPG/PNG/WEBP или PDF.")
        return
    raw, filename, mime = payload

    try:
        check = await ReceiptAnalyzer(settings).analyze(raw, filename, mime)
    except Exception:
        LOGGER.exception("PAYMENT_RECEIPT_AI_FAILED user=%s", user_id)
        await message.answer(
            "⚠️ Сейчас не удалось выполнить обязательную AI-проверку чека. Документ остаётся заблокирован. Отправьте чек ещё раз позже."
            if language != "kk"
            else
            "⚠️ Қазір чекті міндетті AI-тексеру орындалмады. Құжат бұғатталған күйде қалады. Чекті кейін қайта жіберіңіз."
        )
        return

    hard_issues = receipt_hard_issues(check, settings.document_price_kzt)
    if hard_issues:
        LOGGER.warning("PAYMENT_AI_REJECTED user=%s kind=%s issues=%s", user_id, kind, hard_issues[:6])
        await message.answer(
            ("❌ Чек не прошёл автоматическую проверку:\n• " + "\n• ".join(hard_issues[:6]) + "\n\nДокумент не запущен и не выдан. Пришлите полный корректный чек.")
            if language != "kk"
            else
            ("❌ Чек автоматты тексеруден өтпеді:\n• " + "\n• ".join(hard_issues[:6]) + "\n\nҚұжат іске қосылған жоқ және берілген жоқ. Толық дұрыс чекті жіберіңіз.")
        )
        return

    release_guard = can_release_paid_document(
        kind=kind,
        receipt_submitted=True,
        receipt_precheck_passed=True,
        ai_verified=True,
    )
    if not release_guard.allowed:
        LOGGER.critical("PAYMENT_AI_RELEASE_GUARD_BLOCKED user=%s kind=%s reason=%s", user_id, kind, release_guard.reason)
        await message.answer("Документ не выдан: защищённая проверка оплаты не завершена.")
        return

    LOGGER.info(
        "PAYMENT_AI_VERIFIED user=%s kind=%s transaction=%s receipt_id=%s amount=%s",
        user_id,
        kind,
        transaction_id,
        check.receipt_or_transaction_id[:80],
        check.amount_kzt,
    )

    # Negative ids are the current hard-prepay flow: no document exists yet.
    # The verified receipt starts legal research/generation immediately.
    if transaction_id < 0:
        from korgan.prepayment_runtime import run_ai_verified_prepayment_generation

        await run_ai_verified_prepayment_generation(
            message=message,
            state=state,
            user_id=user_id,
            transaction_id=transaction_id,
            kind=kind,
            language=language,
        )
        return

    # Positive ids are legacy held documents generated by an older deployment.
    # Keep them recoverable, but release automatically after the same strict AI
    # verification instead of asking the administrator to confirm.
    storage_admin_id = next((admin_id for admin_id in sorted(settings.admin_ids) if admin_id != user_id), None)
    if storage_admin_id is None:
        LOGGER.error("PAYMENT_LEGACY_STORAGE_MISSING user=%s kind=%s", user_id, kind)
        await message.answer("Оплата проверена, но старый сохранённый документ недоступен. Обратитесь в техподдержку; повторно платить не нужно.")
        return
    try:
        await message.bot.copy_message(
            chat_id=user_id,
            from_chat_id=storage_admin_id,
            message_id=transaction_id,
            caption=_document_caption_with_review(kind, language),
            reply_markup=_document_review_markup(kind, language),
        )
    except Exception:
        LOGGER.exception("PAYMENT_LEGACY_AUTO_RELEASE_FAILED user=%s doc_msg=%s", user_id, transaction_id)
        await message.answer("Оплата проверена, но старый документ не удалось выдать. Повторно платить не нужно; обратитесь в техподдержку.")
        return

    await state.update_data(mode="main")
    LOGGER.info("PAYMENT_AI_VERIFIED_LEGACY_RELEASE user=%s kind=%s transaction=%s", user_id, kind, transaction_id)
    await message.answer(
        "✅ KORGAN AI проверил чек. Оплата принята, Word-файл выдан выше."
        if language != "kk"
        else
        "✅ KORGAN AI чекті тексерді. Төлем қабылданды, Word-файл жоғарыда берілді."
    )


@router.callback_query(F.data.startswith("pay:ok:") | F.data.startswith("pay:no:"))
async def admin_payment_decision(callback: CallbackQuery) -> None:
    """Legacy recovery for admin cards sent before automatic verification deploy."""
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
