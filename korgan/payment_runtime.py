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
    admin_decision_markup,
    admin_receipt_summary,
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
            "💳 Төлем Kaspi арқылы жүргізіледі. Word-файл төлем расталғаннан кейін ғана беріледі.\n\n"
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
            "💳 Оплата через Kaspi. Word-файл выдаётся только после подтверждения оплаты.\n\n"
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
            "📎 Төлем чегін толық түрде фото немесе PDF ретінде жіберіңіз. Сома, күн/уақыт және төлем мәртебесі көрінуі керек."
            if language == "kk"
            else
            "📎 Пришлите полный чек оплаты фото или PDF. Должны быть видны сумма, дата/время и статус платежа."
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
    settings = get_settings()
    data = await state.get_data()
    user_id = message.from_user.id if message.from_user else None
    if user_id is None:
        return

    try:
        admin_doc_message_id = int(data.get("payment_admin_doc_message_id"))
    except (TypeError, ValueError):
        await state.update_data(mode="main")
        await message.answer("Платёжная сессия устарела. Нажмите «✅ Я оплатил» под карточкой оплаты ещё раз.")
        return
    kind = str(data.get("payment_kind") or "")
    language = str(data.get("payment_language") or "ru")
    signature = str(data.get("payment_signature") or "")
    if not verify_user_payment(settings, signature, user_id, admin_doc_message_id, kind, language):
        await state.update_data(mode="main")
        await message.answer("Платёжная сессия устарела. Нажмите «✅ Я оплатил» ещё раз.")
        return

    admins = sorted(settings.admin_ids)
    if not admins:
        LOGGER.error("PAYMENT_NO_ADMIN receipt user=%s", user_id)
        await message.answer("Не удалось передать оплату на подтверждение. Обратитесь в техподдержку; документ не разблокирован.")
        return
    admin_id = admins[0]

    payload = await _receipt_bytes(message)
    if payload is None:
        await message.answer("Не удалось прочитать файл. Пришлите полный чек как фото, JPG/PNG/WEBP или PDF.")
        return
    raw, filename, mime = payload

    try:
        check = await ReceiptAnalyzer(settings).analyze(raw, filename, mime)
    except Exception:
        # The client explicitly requires verification before release. If the AI
        # receipt check is unavailable, do not create an admin approval button:
        # there must be no path from an unchecked receipt to document delivery.
        LOGGER.exception("PAYMENT_RECEIPT_AI_FAILED user=%s", user_id)
        await message.answer(
            "⚠️ Сейчас не удалось выполнить обязательную проверку чека. "
            "Документ остаётся заблокирован и не будет выдан без проверки. Попробуйте отправить чек ещё раз позже."
            if language != "kk"
            else
            "⚠️ Қазір чекті міндетті тексеру орындалмады. Құжат бұғатталған күйде қалады және тексерусіз берілмейді. Чекті кейін қайта жіберіңіз."
        )
        return

    hard_issues = receipt_hard_issues(check, settings.document_price_kzt)
    if hard_issues:
        await message.answer(
            "❌ Чек не прошёл предварительную проверку:\n• "
            + "\n• ".join(hard_issues[:5])
            + "\n\nПришлите полный корректный чек. Документ пока не выдан."
        )
        return

    release_guard = can_release_paid_document(
        kind=kind,
        receipt_submitted=True,
        receipt_precheck_passed=True,
        admin_confirmed=False,
    )
    if release_guard.allowed:
        # Defensive invariant: no document should ever be releasable before the
        # explicit administrator confirmation step below.
        LOGGER.critical("PAYMENT_GUARD_INVALID_PREADMIN_RELEASE user=%s kind=%s", user_id, kind)
        await message.answer("Документ не выдан: ошибка защищённой проверки оплаты. Обратитесь в техподдержку.")
        return

    try:
        await message.bot.copy_message(chat_id=admin_id, from_chat_id=message.chat.id, message_id=message.message_id)
        summary = admin_receipt_summary(
            check,
            user_id=user_id,
            kind=kind,
            language=language,
            amount=settings.document_price_kzt,
        )
        await message.bot.send_message(
            admin_id,
            summary,
            reply_markup=admin_decision_markup(settings, user_id, admin_doc_message_id, kind, language),
        )
    except Exception:
        LOGGER.exception("PAYMENT_ADMIN_FORWARD_FAILED user=%s", user_id)
        await message.answer("Не удалось передать чек на подтверждение. Документ не разблокирован. Попробуйте ещё раз позже.")
        return

    await state.update_data(mode="main")
    await message.answer(
        "✅ Чек принят. Он прошёл предварительную AI-проверку и отправлен на финальное подтверждение оплаты. "
        "Word-файл будет выдан только после сверки платежа администратором."
        if language != "kk"
        else
        "✅ Чек қабылданды. Ол алдын ала AI-тексеруден өтіп, төлемді соңғы растауға жіберілді. Word-файл әкімші төлемді тексергеннен кейін ғана беріледі."
    )


@router.callback_query(F.data.startswith("pay:ok:") | F.data.startswith("pay:no:"))
async def admin_payment_decision(callback: CallbackQuery) -> None:
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
        await callback.bot.send_message(
            user_id,
            "❌ Оплату пока не удалось подтвердить. Проверьте платёж/чек и нажмите «✅ Я оплатил» под карточкой оплаты повторно. "
            "Документ не выдан."
        )
        return

    release_guard = can_release_paid_document(
        kind=kind,
        receipt_submitted=True,
        receipt_precheck_passed=True,
        admin_confirmed=True,
    )
    if not release_guard.allowed:
        LOGGER.error("PAYMENT_RELEASE_GUARD_BLOCKED user=%s kind=%s reason=%s", user_id, kind, release_guard.reason)
        await callback.answer("Документ остаётся заблокирован: проверка оплаты не завершена.", show_alert=True)
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
        LOGGER.exception("PAYMENT_DOCUMENT_RELEASE_FAILED user=%s doc_msg=%s", user_id, admin_doc_message_id)
        await callback.answer("Не удалось выдать документ. Решение не зафиксировано — повторите.", show_alert=True)
        return

    await callback.answer("Оплата подтверждена, документ выдан.")
    await callback.message.edit_text(current_text + "\n\n✅ ОПЛАТА ПОДТВЕРЖДЕНА — документ выдан клиенту.", reply_markup=None)
    await callback.bot.send_message(
        user_id,
        "✅ Оплата подтверждена. Word-файл выдан выше."
        if language != "kk"
        else
        "✅ Төлем расталды. Word-файл жоғарыда берілді."
    )
