from __future__ import annotations

import hashlib
import hmac
import logging

from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from korgan import prepayment_gate
from korgan.config import Settings, get_settings
from korgan.i18n import KK, normalize_language
from korgan.payment import payment_offer_markup

LOGGER = logging.getLogger(__name__)


def prepayment_transaction_id(settings: Settings, user_id: int, request_id: str, kind: str) -> int:
    """Create a stable negative id for one immutable pre-generation request.

    Negative ids are already the canonical namespace used by the existing
    automatic receipt -> paid-generation flow. The id is derived from the bot
    secret and request scope, so no Telegram admin/storage message is needed.
    """
    body = f"prepay:{int(user_id)}:{request_id}:{kind}".encode("utf-8")
    digest = hmac.new(settings.telegram_bot_token.encode("utf-8"), body, hashlib.sha256).digest()
    value = int.from_bytes(digest[:8], "big") & ((1 << 63) - 1)
    return -(value or 1)


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
            "💳 Оплата по этой заявке уже ожидается. Используйте карточку оплаты выше и после оплаты пришлите чек — KORGAN AI проверит его автоматически."
            if language != KK
            else "💳 Бұл өтінім бойынша төлем күтілуде. Жоғарыдағы төлем карточкасын пайдаланып, төлемнен кейін чекті жіберіңіз — KORGAN AI оны автоматты түрде тексереді."
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
        prepayment_gate.prepayment_offer_text(kind, language, settings.document_price_kzt),
        reply_markup=payment_offer_markup(settings, user_id, transaction_id, kind, language),
    )
    LOGGER.info(
        "PREPAY_OFFERED_AUTO user=%s request_id=%s kind=%s transaction=%s amount=%s admin_chat=not_required",
        user_id,
        request_id,
        kind,
        transaction_id,
        settings.document_price_kzt,
    )
    return False


def install_adminless_automatic_prepayment() -> None:
    """Patch only prepayment reservation creation; all downstream gates stay unchanged."""
    prepayment_gate.ensure_prepayment = ensure_prepayment_without_admin
    # Expose the deterministic id for diagnostics/regression tests without
    # changing legacy callback parsers or paid-delivery semantics.
    prepayment_gate._prepayment_transaction_id = prepayment_transaction_id
    LOGGER.info("KORGAN automatic prepayment installed: admin chat not required")
