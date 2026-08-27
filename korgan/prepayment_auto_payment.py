from __future__ import annotations

import hashlib
import hmac
import logging

from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from korgan import prepayment_gate
from korgan.config import Settings, get_settings
from korgan.i18n import KK, normalize_language
from korgan.payment import document_label, payment_offer_markup

LOGGER = logging.getLogger(__name__)


def prepayment_transaction_id(settings: Settings, user_id: int, request_id: str, kind: str) -> int:
    """Create a stable negative id for one immutable pre-generation request."""
    body = f"prepay:{int(user_id)}:{request_id}:{kind}".encode("utf-8")
    digest = hmac.new(settings.telegram_bot_token.encode("utf-8"), body, hashlib.sha256).digest()
    value = int.from_bytes(digest[:8], "big") & ((1 << 63) - 1)
    return -(value or 1)


def fiscal_qr_prepayment_offer_text(kind: str, language: str, amount: int) -> str:
    label = document_label(kind, language)
    amount_text = f"{amount:,}".replace(",", " ")
    if language == KK:
        return (
            "💳 Құжатты дайындау алдындағы төлем\n\n"
            f"Қызмет құны: {amount_text} ₸\n"
            f"Құжат: {label}.\n\n"
            "AI құжатты әлі дайындаған жоқ. Құқықтық талдау және Word-файлды қалыптастыру "
            "төлем тексерілгеннен кейін ғана басталады.\n\n"
            "1. Kaspi арқылы төлеңіз.\n"
            "2. «✅ Төледім» түймесін басыңыз.\n"
            "3. Фискалдық чектегі QR-кодты сканерлеп, ашылған receipt.kaspi.kz сілтемесін жіберіңіз.\n\n"
            "KORGAN төлемді Kaspi ОФД деректері бойынша автоматты тексереді. AI төлем туралы шешім қабылдамайды."
        )
    return (
        "💳 Оплата перед подготовкой документа\n\n"
        f"Стоимость: {amount_text} ₸\n"
        f"Документ: {label}.\n\n"
        "AI ещё не формировал документ. Юридический анализ и подготовка Word-файла начнутся "
        "только после проверки оплаты.\n\n"
        "1. Оплатите через Kaspi.\n"
        "2. Нажмите «✅ Я оплатил».\n"
        "3. Отсканируйте QR на фискальном чеке и пришлите открывшуюся ссылку receipt.kaspi.kz.\n\n"
        "KORGAN автоматически сверит оплату по данным Kaspi ОФД. AI не принимает решение об оплате."
    )


async def ensure_prepayment_without_admin(message: Message, state: FSMContext, *, kind: str) -> bool:
    """Open automatic Kaspi prepayment without depending on an admin chat."""
    settings = get_settings()
    if not settings.payments_enabled:
        return True

    data = await state.get_data()
    request_id = str(data.get("request_id") or "")
    request_kind = str(data.get("request_kind") or "")
    language = normalize_language(str(data.get("language") or "ru"))

    if not request_id or request_kind != kind:
        LOGGER.error(
            "PREPAY_REQUEST_SCOPE_MISSING chat=%s request_id=%r state_kind=%r expected_kind=%s",
            getattr(message.chat, "id", None),
            request_id,
            request_kind,
            kind,
        )
        await message.answer(
            "Не удалось безопасно открыть оплату для этой заявки. Откройте «📄 Документ» и выберите документ заново."
            if language != KK
            else "Бұл өтінім үшін төлемді қауіпсіз ашу мүмкін болмады. «📄 Құжат» бөлімін ашып, құжатты қайта таңдаңыз."
        )
        return False

    if str(data.get("prepayment_consumed_request_id") or "") == request_id:
        await message.answer(
            "Документ по этой оплаченной заявке уже запускался. Для нового документа откройте новую заявку."
            if language != KK
            else "Осы төленген өтінім бойынша құжат бұрын іске қосылған. Жаңа құжат үшін жаңа өтінім ашыңыз."
        )
        return False

    if (
        str(data.get("prepayment_confirmed_request_id") or "") == request_id
        and str(data.get("prepayment_confirmed_kind") or "") == kind
    ):
        return True

    existing_transaction = data.get("prepayment_transaction_id")
    if (
        existing_transaction is not None
        and str(data.get("prepayment_request_id") or "") == request_id
        and str(data.get("prepayment_kind") or "") == kind
    ):
        await state.update_data(mode="prepayment_waiting")
        await message.answer(
            "💳 Оплата по этой заявке уже ожидается. После оплаты нажмите «✅ Я оплатил», отсканируйте QR фискального чека и пришлите ссылку receipt.kaspi.kz."
            if language != KK
            else "💳 Бұл өтінім бойынша төлем күтілуде. Төлемнен кейін «✅ Төледім» түймесін басып, фискалдық чектің QR-кодын сканерлеп, receipt.kaspi.kz сілтемесін жіберіңіз."
        )
        return False

    try:
        user_id = int(message.chat.id)
    except (TypeError, ValueError):
        LOGGER.error("PREPAY_INVALID_CLIENT_CHAT chat=%r kind=%s", getattr(message.chat, "id", None), kind)
        return False

    if not settings.kaspi_payment_url.strip():
        LOGGER.error("PREPAY_CONFIG_ERROR kaspi_url=False user=%s", user_id)
        await message.answer(
            "Оплата временно недоступна из-за технической настройки. Подготовка документа не начата. Обратитесь в техподдержку."
            if language != KK
            else "Техникалық баптауға байланысты төлем уақытша қолжетімсіз. Құжатты дайындау басталған жоқ. Техқолдауға жүгініңіз."
        )
        return False

    transaction_id = prepayment_transaction_id(settings, user_id, request_id, kind)

    latest = await state.get_data()
    if (
        str(latest.get("request_id") or "") != request_id
        or str(latest.get("request_kind") or "") != kind
    ):
        LOGGER.info("STALE_PREPAY_SUPPRESSED user=%s request_id=%s kind=%s", user_id, request_id, kind)
        return False

    await state.update_data(
        mode="prepayment_waiting",
        prepayment_transaction_id=transaction_id,
        prepayment_request_id=request_id,
        prepayment_kind=kind,
        prepayment_language=language,
    )
    await message.answer(
        fiscal_qr_prepayment_offer_text(kind, language, settings.document_price_kzt),
        reply_markup=payment_offer_markup(settings, user_id, transaction_id, kind, language),
    )
    LOGGER.info(
        "PREPAY_OFFERED_OFD user=%s request_id=%s kind=%s transaction=%s amount=%s admin_chat=not_required",
        user_id,
        request_id,
        kind,
        transaction_id,
        settings.document_price_kzt,
    )
    return False


def install_adminless_automatic_prepayment() -> None:
    """Install adminless prepayment while preserving existing generation gates."""
    prepayment_gate.ensure_prepayment = ensure_prepayment_without_admin
    prepayment_gate.prepayment_offer_text = fiscal_qr_prepayment_offer_text
    prepayment_gate._prepayment_transaction_id = prepayment_transaction_id
    LOGGER.info("KORGAN Kaspi OFD prepayment installed: admin chat and AI payment decision not required")
