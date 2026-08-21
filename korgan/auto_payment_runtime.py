from __future__ import annotations

import io
import logging
from asyncio import Lock

from aiogram import Router
from aiogram.filters import BaseFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from korgan.config import get_settings
from korgan.localized_transport import _document_caption_with_review, _document_review_markup
from korgan.payment import ReceiptAnalyzer, receipt_fingerprint, receipt_hard_issues, verify_user_payment
from korgan.payment_release_guard import can_release_paid_document

LOGGER = logging.getLogger(__name__)
router = Router(name="korgan-auto-payment-runtime")
_RELEASE_LOCKS: dict[str, Lock] = {}


def _transaction_key(user_id: int, admin_doc_message_id: int, kind: str, language: str) -> str:
    return f"{user_id}:{admin_doc_message_id}:{kind}:{language}"


class AutoPaymentReceiptFilter(BaseFilter):
    async def __call__(self, message: Message, state: FSMContext) -> bool:
        data = await state.get_data()
        return data.get("mode") == "payment_receipt" and bool(message.photo or message.document)


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


def install_auto_payment() -> None:
    """Update client payment copy; the document hold mechanism stays unchanged."""
    from korgan import payment_gate

    def auto_payment_offer_text(kind: str, language: str, amount: int) -> str:
        from korgan.payment import document_label

        label = document_label(kind, language)
        formatted = f"{amount:,}".replace(",", " ")
        if language == "kk":
            return (
                "💳 Құжат дайын\n\n"
                f"Қызмет құны: {formatted} ₸\n"
                f"Құжат: {label}.\n\n"
                "Word-файл чек KORGAN AI-тексеруден және әкімшінің төлемді растауынан кейін беріледі.\n"
                "1. Kaspi арқылы төлеңіз.\n"
                "2. «✅ Төледім» түймесін басыңыз.\n"
                "3. Толық чекті фото немесе PDF түрінде жіберіңіз.\n\n"
                "AI чек сомасын, сәтті төлем мәртебесін және көрінетін реквизиттерді тексереді. Содан кейін әкімші төлемді Kaspi тарихымен салыстырады."
            )
        return (
            "💳 Документ готов\n\n"
            f"Стоимость: {formatted} ₸\n"
            f"Документ: {label}.\n\n"
            "Word-файл будет выдан после проверки чека KORGAN AI и подтверждения платежа администратором.\n"
            "1. Оплатите через Kaspi.\n"
            "2. Нажмите «✅ Я оплатил».\n"
            "3. Пришлите полный чек фото или PDF.\n\n"
            "AI проверит сумму, успешный статус платежа и видимые реквизиты. Затем администратор сверит платёж с историей Kaspi."
        )

    payment_gate.payment_offer_text = auto_payment_offer_text


@router.message(AutoPaymentReceiptFilter())
async def auto_payment_receipt_received(message: Message, state: FSMContext) -> None:
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

    transaction_key = _transaction_key(user_id, admin_doc_message_id, kind, language)

    admins = sorted(settings.admin_ids)
    if not admins:
        LOGGER.error("AUTO_PAYMENT_NO_STORAGE_ADMIN user=%s", user_id)
        await message.answer("Не удалось получить зарезервированный документ. Оплата не подтверждена; обратитесь в техподдержку.")
        return
    admin_id = admins[0]

    payload = await _receipt_bytes(message)
    if payload is None:
        await message.answer(
            "📎 Чек оқылмады. Толық чекті фото, JPG/PNG/WEBP немесе PDF түрінде қайта жіберіңіз."
            if language == "kk"
            else "📎 Не удалось прочитать чек. Пришлите полный чек как фото, JPG/PNG/WEBP или PDF."
        )
        return

    raw, filename, mime = payload
    try:
        check = await ReceiptAnalyzer(settings).analyze(raw, filename, mime)
    except Exception:
        LOGGER.exception("AUTO_PAYMENT_AI_FAILED user=%s", user_id)
        await message.answer(
            "⚠️ AI чекті тексере алмады. Құжат ашылған жоқ. Чекті қайта жіберіңіз."
            if language == "kk"
            else "⚠️ AI не смог проверить чек. Документ не разблокирован. Пришлите чек повторно."
        )
        return

    issues = receipt_hard_issues(check, settings.document_price_kzt)
    if check.suspicious_signals:
        issues.extend(f"AI обнаружил подозрительный признак: {item}" for item in check.suspicious_signals[:3])

    if issues:
        LOGGER.warning("AUTO_PAYMENT_REJECTED user=%s issues=%s", user_id, issues[:5])
        if language == "kk":
            await message.answer(
                "❌ Чек AI-тексеруден өтпеді:\n• " + "\n• ".join(issues[:5])
                + "\n\nТолық дұрыс чекті қайта жіберіңіз. Құжат берілген жоқ."
            )
        else:
            await message.answer(
                "❌ Чек не прошёл AI-проверку:\n• " + "\n• ".join(issues[:5])
                + "\n\nПришлите полный корректный чек. Документ пока не выдан."
            )
        return

    receipt_hash = receipt_fingerprint(raw)
    release_lock = _RELEASE_LOCKS.setdefault(transaction_key, Lock())
    async with release_lock:
        latest = await state.get_data()
        try:
            latest_doc_message_id = int(latest.get("payment_admin_doc_message_id"))
        except (TypeError, ValueError):
            latest_doc_message_id = 0
        if (
            latest_doc_message_id != admin_doc_message_id
            or str(latest.get("payment_kind") or "") != kind
            or str(latest.get("payment_language") or "ru") != language
            or not verify_user_payment(
                settings,
                str(latest.get("payment_signature") or ""),
                user_id,
                admin_doc_message_id,
                kind,
                language,
            )
        ):
            await message.answer("Платёжная сессия изменилась. Откройте нужную заявку и отправьте чек заново.")
            return

        accepted_fingerprints = {
            str(item) for item in latest.get("payment_accepted_receipt_fingerprints", []) or []
        }
        released_transactions = dict(latest.get("payment_released_transactions", {}) or {})
        if receipt_hash in accepted_fingerprints or released_transactions.get(transaction_key) is True:
            await message.answer(
                "❌ Этот чек уже использован либо документ по этой платёжной операции уже выдан."
                if language != "kk"
                else "❌ Бұл чек бұрын пайдаланылған немесе осы төлем операциясы бойынша құжат берілген."
            )
            return

        release_guard = can_release_paid_document(
            kind=kind,
            receipt_submitted=True,
            receipt_precheck_passed=True,
            admin_confirmed=(
                str(latest.get("payment_admin_confirmed_transaction_key") or "") == transaction_key
            ),
        )
        if not release_guard.allowed:
            LOGGER.warning(
                "AUTO_PAYMENT_RELEASE_GUARD_BLOCKED user=%s kind=%s reason=%s",
                user_id,
                kind,
                release_guard.reason,
            )
            await message.answer(
                "✅ Чек прошёл предварительную AI-проверку. Документ остаётся заблокирован до подтверждения оплаты администратором."
                if language != "kk"
                else "✅ Чек алдын ала AI-тексеруден өтті. Әкімші төлемді растағанға дейін құжат бұғатталған күйде қалады."
            )
            return

        # Claim the receipt and transaction before delivery. A failed copy is
        # handled by support instead of allowing a replay to send two documents.
        accepted_fingerprints.add(receipt_hash)
        released_transactions[transaction_key] = True
        await state.update_data(
            mode="main",
            payment_accepted_receipt_fingerprints=sorted(accepted_fingerprints),
            payment_released_transactions=released_transactions,
        )

        try:
            await message.bot.copy_message(
                chat_id=user_id,
                from_chat_id=admin_id,
                message_id=admin_doc_message_id,
                caption=_document_caption_with_review(kind, language),
                reply_markup=_document_review_markup(kind, language),
            )
        except Exception:
            LOGGER.exception("AUTO_PAYMENT_DOCUMENT_RELEASE_FAILED user=%s doc_msg=%s", user_id, admin_doc_message_id)
            await message.answer(
                "Оплата подтверждена, но Word-файл не удалось выдать из технического хранилища. Обратитесь в техподдержку; повторно оплачивать не нужно."
                if language != "kk"
                else "Төлем расталды, бірақ Word-файлды техникалық қоймадан беру мүмкін болмады. Қолдауға жазыңыз; қайта төлеудің қажеті жоқ."
            )
            return

    LOGGER.info(
        "AUTO_PAYMENT_ACCEPTED user=%s kind=%s amount=%s transaction=%s",
        user_id,
        kind,
        check.amount_kzt,
        check.receipt_or_transaction_id[:80],
    )
    await message.answer(
        "✅ Чек прошёл AI-проверку. Оплата принята, Word-файл выдан выше."
        if language != "kk"
        else "✅ Чек AI-тексеруден өтті. Төлем қабылданды, Word-файл жоғарыда берілді."
    )
