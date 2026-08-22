from __future__ import annotations

import hashlib
import hmac
import logging
from contextvars import ContextVar, Token

from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from korgan import bot as base_bot
from korgan.config import Settings, get_settings
from korgan.i18n import KK, normalize_language
from korgan.payment import document_label, payment_offer_markup

LOGGER = logging.getLogger(__name__)
_INSTALLED = False
_PAID_DELIVERY: ContextVar[tuple[int, str] | None] = ContextVar(
    "korgan_paid_document_delivery",
    default=None,
)


def begin_paid_delivery(user_id: int, kind: str) -> Token[tuple[int, str] | None]:
    """Authorize DOCX delivery only inside one confirmed generation task."""
    return _PAID_DELIVERY.set((int(user_id), str(kind)))


def end_paid_delivery(token: Token[tuple[int, str] | None]) -> None:
    _PAID_DELIVERY.reset(token)


def is_paid_delivery_authorized(user_id: int, kind: str) -> bool:
    """True only while an admin-confirmed paid generation is executing."""
    return _PAID_DELIVERY.get() == (int(user_id), str(kind))


def _secret(settings: Settings) -> bytes:
    return settings.telegram_bot_token.encode("utf-8")


def sign_paid_generation(
    settings: Settings,
    user_id: int,
    transaction_id: int,
    kind: str,
    language: str,
) -> str:
    body = f"generate:{user_id}:{transaction_id}:{kind}:{language}".encode("utf-8")
    return hmac.new(_secret(settings), body, hashlib.sha256).hexdigest()[:12]


def verify_paid_generation(
    settings: Settings,
    signature: str,
    user_id: int,
    transaction_id: int,
    kind: str,
    language: str,
) -> bool:
    expected = sign_paid_generation(settings, user_id, transaction_id, kind, language)
    return hmac.compare_digest(signature, expected)


def paid_generation_markup(
    settings: Settings,
    user_id: int,
    transaction_id: int,
    kind: str,
    language: str,
) -> InlineKeyboardMarkup:
    signature = sign_paid_generation(settings, user_id, transaction_id, kind, language)
    text = "⚙️ Құжатты дайындау" if language == KK else "⚙️ Подготовить документ"
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(
            text=text,
            callback_data=f"pay:generate:{transaction_id}:{kind}:{language}:{signature}",
        )]]
    )


def prepayment_offer_text(kind: str, language: str, amount: int) -> str:
    label = document_label(kind, language)
    amount_text = f"{amount:,}".replace(",", " ")
    if language == KK:
        return (
            "💳 Құжатты дайындау алдындағы төлем\n\n"
            f"Қызмет құны: {amount_text} ₸\n"
            f"Құжат: {label}.\n\n"
            "AI құжатты әлі дайындаған жоқ. Құжатты құқықтық талдау және Word-файлды қалыптастыру "
            "төлем расталғаннан кейін ғана басталады.\n\n"
            "1. Kaspi арқылы төлеңіз.\n"
            "2. «✅ Төледім» түймесін басыңыз.\n"
            "3. Толық чекті жіберіңіз.\n\n"
            "Чек алдымен AI арқылы тексеріледі, содан кейін әкімші нақты төлемді Kaspi Pay тарихымен растайды."
        )
    return (
        "💳 Оплата перед подготовкой документа\n\n"
        f"Стоимость: {amount_text} ₸\n"
        f"Документ: {label}.\n\n"
        "AI ещё не формировал документ. Юридический анализ и подготовка Word-файла начнутся "
        "только после подтверждения оплаты.\n\n"
        "1. Оплатите через Kaspi.\n"
        "2. Нажмите «✅ Я оплатил».\n"
        "3. Пришлите полный чек.\n\n"
        "Чек сначала проходит AI-проверку, затем администратор подтверждает фактический платёж по истории Kaspi Pay."
    )


def _reservation_text(user_id: int, request_id: str, kind: str, language: str, amount: int) -> str:
    return (
        "🔒 KORGAN PREPAY RESERVATION\n"
        f"Клиент Telegram ID: {user_id}\n"
        f"Заявка: {request_id}\n"
        f"Документ: {document_label(kind, language)}\n"
        f"Сумма: {amount} ₸\n"
        "Документ ещё НЕ генерировался. Ожидается подтверждение оплаты."
    )


def _safe_admin(admin_ids: set[int] | frozenset[int], user_id: int) -> int | None:
    return next((admin_id for admin_id in sorted(admin_ids) if admin_id != user_id), None)


async def ensure_prepayment(message: Message, state: FSMContext, *, kind: str) -> bool:
    """Return True only when the current request may start expensive drafting.

    Intake stays free: the client may describe the matter and upload materials.
    Once the request has enough material to enter legal research/drafting, this
    gate creates a payment transaction instead. No research or DOCX generation is
    allowed until the receipt passes AI pre-check and an administrator confirms
    the payment.
    """
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
            else
            "Бұл өтінім үшін төлемді қауіпсіз ашу мүмкін болмады. «📄 Құжат» бөлімін ашып, құжатты қайта таңдаңыз."
        )
        return False

    if str(data.get("prepayment_consumed_request_id") or "") == request_id:
        await message.answer(
            "Документ по этой оплаченной заявке уже запускался. Для нового документа откройте новую заявку."
            if language != KK
            else
            "Осы төленген өтінім бойынша құжат бұрын іске қосылған. Жаңа құжат үшін жаңа өтінім ашыңыз."
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
            "💳 Оплата по этой заявке уже ожидается. Используйте карточку оплаты выше и после оплаты пришлите чек."
            if language != KK
            else
            "💳 Бұл өтінім бойынша төлем күтілуде. Жоғарыдағы төлем карточкасын пайдаланып, төлемнен кейін чекті жіберіңіз."
        )
        return False

    try:
        user_id = int(message.chat.id)
    except (TypeError, ValueError):
        LOGGER.error("PREPAY_INVALID_CLIENT_CHAT chat=%r kind=%s", getattr(message.chat, "id", None), kind)
        return False

    storage_admin_id = _safe_admin(settings.admin_ids, user_id)
    if not settings.kaspi_payment_url.strip() or storage_admin_id is None:
        LOGGER.error(
            "PREPAY_CONFIG_ERROR kaspi_url=%s admin_count=%s safe_admin=%s user=%s",
            bool(settings.kaspi_payment_url.strip()),
            len(settings.admin_ids),
            storage_admin_id is not None,
            user_id,
        )
        await message.answer(
            "Оплата временно недоступна из-за технической настройки. Подготовка документа не начата. Обратитесь в техподдержку."
            if language != KK
            else
            "Техникалық баптауға байланысты төлем уақытша қолжетімсіз. Құжатты дайындау басталған жоқ. Техқолдауға жүгініңіз."
        )
        return False

    try:
        reservation = await message.bot.send_message(
            storage_admin_id,
            _reservation_text(user_id, request_id, kind, language, settings.document_price_kzt),
        )
    except Exception:
        LOGGER.exception("PREPAY_RESERVATION_FAILED user=%s kind=%s", user_id, kind)
        await message.answer(
            "Не удалось безопасно открыть оплату. Подготовка документа не начата. Попробуйте позже."
            if language != KK
            else
            "Төлемді қауіпсіз ашу мүмкін болмады. Құжатты дайындау басталған жоқ. Кейінірек қайталап көріңіз."
        )
        return False

    # Negative ids are reserved for pre-generation payment transactions. Legacy
    # positive ids still identify already-generated held documents and remain
    # releasable through the old compatibility flow.
    transaction_id = -int(reservation.message_id)

    # A client can switch document types while the admin reservation is being
    # created. Never show a payment card for a request that is no longer current.
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
        prepayment_offer_text(kind, language, settings.document_price_kzt),
        reply_markup=payment_offer_markup(settings, user_id, transaction_id, kind, language),
    )
    LOGGER.info(
        "PREPAY_OFFERED user=%s request_id=%s kind=%s transaction=%s amount=%s",
        user_id,
        request_id,
        kind,
        transaction_id,
        settings.document_price_kzt,
    )
    return False


async def _context(state: FSMContext) -> str:
    return await base_bot._case_context(state)


def install_generation_prepayment_gate() -> None:
    """Patch every active legal-document generator with the same prepay rule."""
    global _INSTALLED
    if _INSTALLED:
        return

    from korgan import pretrial_response_runtime, pretrial_runtime, universal_claim_runtime, universal_document_runtime

    original_claim = universal_claim_runtime._generate_now
    original_pretrial = pretrial_runtime._generate
    original_pretrial_response = pretrial_response_runtime._generate
    original_contract = universal_document_runtime._send_contract
    original_response = universal_document_runtime._send_response

    async def claim_guarded(message: Message, state: FSMContext) -> None:
        context = await _context(state)
        if not context.strip():
            await original_claim(message, state)
            return
        if not await ensure_prepayment(message, state, kind="claim"):
            return
        await original_claim(message, state)

    async def pretrial_guarded(message: Message, state: FSMContext) -> None:
        await pretrial_runtime._save_text(message, state)
        context = await _context(state)
        if not context.strip():
            await original_pretrial(message, state)
            return
        if not await ensure_prepayment(message, state, kind="pretrial"):
            return
        await original_pretrial(message, state)

    async def pretrial_response_guarded(message: Message, state: FSMContext) -> None:
        await pretrial_response_runtime._save_text(message, state)
        context = await _context(state)
        if not pretrial_response_runtime._looks_like_pretrial_materials(context):
            await original_pretrial_response(message, state)
            return
        if not await ensure_prepayment(message, state, kind="pretrial_response"):
            return
        await original_pretrial_response(message, state)

    async def contract_guarded(message: Message, state: FSMContext) -> None:
        await universal_document_runtime._save_user_text(message, state, min_length=24)
        context = await _context(state)
        if not context.strip() or len(context.strip()) < 80:
            await original_contract(message, state)
            return
        if not await ensure_prepayment(message, state, kind="contract"):
            return
        await original_contract(message, state)

    async def response_guarded(message: Message, state: FSMContext) -> None:
        await universal_document_runtime._save_user_text(message, state)
        context = await _context(state)
        if not universal_document_runtime._looks_like_claim_materials(context):
            await original_response(message, state)
            return
        if not await ensure_prepayment(message, state, kind="response"):
            return
        await original_response(message, state)

    universal_claim_runtime._generate_now = claim_guarded
    pretrial_runtime._generate = pretrial_guarded
    pretrial_response_runtime._generate = pretrial_response_guarded
    universal_document_runtime._send_contract = contract_guarded
    universal_document_runtime._send_response = response_guarded

    _INSTALLED = True
    LOGGER.info("KORGAN pre-generation payment gate installed for all legal document types")
