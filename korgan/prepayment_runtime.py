from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import BaseFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from korgan.admin import is_admin
from korgan.config import get_settings
from korgan.i18n import KK
from korgan.payment import verify_admin_action
from korgan.payment_release_guard import can_release_paid_document
from korgan.prepayment_gate import (
    begin_paid_delivery,
    end_paid_delivery,
    paid_generation_markup,
    verify_paid_generation,
)
from korgan.request_scope import is_main_menu_text

LOGGER = logging.getLogger(__name__)
router = Router(name="korgan-prepayment-runtime")


def _parse_admin_callback(data: str) -> tuple[str, int, int, str, str, str] | None:
    """Compatibility parser for payment cards created by older deployments."""
    parts = data.split(":")
    if len(parts) != 7 or parts[0] != "pay" or parts[1] not in {"ok", "no"}:
        return None
    try:
        action = parts[1]
        user_id = int(parts[2])
        transaction_id = int(parts[3])
    except ValueError:
        return None
    if transaction_id >= 0:
        return None
    return action, user_id, transaction_id, parts[4], parts[5], parts[6]


def _parse_generation_callback(data: str) -> tuple[int, str, str, str] | None:
    """Compatibility parser for already-sent legacy generation buttons."""
    parts = data.split(":")
    if len(parts) != 6 or parts[:2] != ["pay", "generate"]:
        return None
    try:
        transaction_id = int(parts[2])
    except ValueError:
        return None
    if transaction_id >= 0:
        return None
    return transaction_id, parts[3], parts[4], parts[5]


class PrepayAdminDecisionFilter(BaseFilter):
    async def __call__(self, callback: CallbackQuery):
        parsed = _parse_admin_callback(callback.data or "")
        return {"prepay_admin_decision": parsed} if parsed is not None else False


class PaidGenerationFilter(BaseFilter):
    async def __call__(self, callback: CallbackQuery):
        parsed = _parse_generation_callback(callback.data or "")
        return {"paid_generation": parsed} if parsed is not None else False


class PrepaymentWaitingTextFilter(BaseFilter):
    async def __call__(self, message: Message, state: FSMContext) -> bool:
        data = await state.get_data()
        text = message.text or ""
        return (
            data.get("mode") == "prepayment_waiting"
            and bool(text)
            and not text.startswith("/")
            and not is_main_menu_text(text)
        )


@router.message(PrepaymentWaitingTextFilter(), F.text)
async def prepayment_waiting_text(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    language = str(data.get("prepayment_language") or data.get("language") or "ru")
    await message.answer(
        "💳 Бұл өтінім бойынша құжатты дайындау төлем AI арқылы тексерілгенге дейін басталмайды. Жоғарыдағы «✅ Төледім» түймесін пайдаланыңыз."
        if language == KK
        else
        "💳 По этой заявке подготовка документа не начнётся, пока KORGAN AI не проверит оплату. Используйте кнопку «✅ Я оплатил» в карточке выше."
    )


@router.callback_query(PrepayAdminDecisionFilter())
async def prepayment_admin_decision(
    callback: CallbackQuery,
    prepay_admin_decision: tuple[str, int, int, str, str, str],
) -> None:
    """Legacy recovery only for payment cards already awaiting an admin."""
    action, user_id, transaction_id, kind, language, signature = prepay_admin_decision
    settings = get_settings()
    admin_id = callback.from_user.id if callback.from_user else None

    if not is_admin(admin_id, settings):
        await callback.answer("Недостаточно прав.", show_alert=True)
        return
    if not verify_admin_action(settings, signature, user_id, transaction_id, kind, language):
        LOGGER.warning("PREPAY_ADMIN_SIGNATURE_REJECTED admin=%s user=%s", admin_id, user_id)
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
            "❌ Оплату пока не удалось подтвердить. Подготовка документа не начиналась. Проверьте платёж/чек и повторно нажмите «✅ Я оплатил» в карточке оплаты."
            if language != KK
            else
            "❌ Төлемді растау мүмкін болмады. Құжатты дайындау басталған жоқ. Төлемді/чекті тексеріп, төлем карточкасындағы «✅ Төледім» түймесін қайта басыңыз."
        )
        return

    decision = can_release_paid_document(
        kind=kind,
        receipt_submitted=True,
        receipt_precheck_passed=True,
        admin_confirmed=True,
    )
    if not decision.allowed:
        LOGGER.error(
            "PREPAY_LEGACY_CONFIRMATION_GUARD_BLOCKED user=%s kind=%s reason=%s",
            user_id,
            kind,
            decision.reason,
        )
        await callback.answer("Нельзя запустить подготовку: проверка оплаты не завершена.", show_alert=True)
        return

    try:
        await callback.bot.send_message(
            user_id,
            (
                "✅ Төлем расталды. Ескі төлем өтінімі үшін құжатты дайындауды төмендегі түймемен іске қосуға болады."
                if language == KK
                else
                "✅ Оплата подтверждена. Для этой старой платёжной заявки документ можно запустить кнопкой ниже."
            ),
            reply_markup=paid_generation_markup(settings, user_id, transaction_id, kind, language),
        )
    except Exception:
        LOGGER.exception("PREPAY_LEGACY_CONFIRMATION_DELIVERY_FAILED user=%s kind=%s", user_id, kind)
        await callback.answer("Не удалось отправить клиенту запуск документа. Повторите.", show_alert=True)
        return

    await callback.answer("Оплата подтверждена для старой заявки.")
    await callback.message.edit_text(
        current_text + "\n\n✅ ОПЛАТА ПОДТВЕРЖДЕНА — legacy recovery.",
        reply_markup=None,
    )


async def _run_paid_generation(kind: str, message: Message, state: FSMContext) -> None:
    # Lazy imports keep the production hotfix/install order unchanged.
    from korgan import pretrial_response_runtime, pretrial_runtime, universal_claim_runtime, universal_document_runtime

    if kind == "claim":
        await universal_claim_runtime._generate_now(message, state)
        return
    if kind == "pretrial":
        await pretrial_runtime._generate(message, state)
        return
    if kind == "pretrial_response":
        await pretrial_response_runtime._generate(message, state)
        return
    if kind == "response":
        await universal_document_runtime._send_response(message, state)
        return
    if kind == "contract":
        await universal_document_runtime._send_contract(message, state)
        return
    raise ValueError(f"Unsupported paid document kind: {kind}")


async def run_ai_verified_prepayment_generation(
    *,
    message: Message,
    state: FSMContext,
    user_id: int,
    transaction_id: int,
    kind: str,
    language: str,
) -> bool:
    """Start one paid generation immediately after strict AI receipt acceptance."""
    data = await state.get_data()
    request_id = str(data.get("request_id") or "")
    if (
        transaction_id >= 0
        or not request_id
        or str(data.get("request_kind") or "") != kind
        or int(data.get("prepayment_transaction_id") or 0) != transaction_id
        or str(data.get("prepayment_request_id") or "") != request_id
        or str(data.get("prepayment_kind") or "") != kind
    ):
        LOGGER.warning(
            "PREPAY_AI_SCOPE_REJECTED user=%s request_id=%s kind=%s transaction=%s",
            user_id,
            request_id,
            kind,
            transaction_id,
        )
        await message.answer(
            "Эта оплата относится к другой или уже закрытой заявке. Документ не запущен."
            if language != KK
            else
            "Бұл төлем басқа немесе жабылған өтінімге қатысты. Құжат іске қосылған жоқ."
        )
        return False

    if str(data.get("prepayment_consumed_request_id") or "") == request_id:
        LOGGER.warning("PREPAY_AI_ALREADY_CONSUMED user=%s request_id=%s", user_id, request_id)
        return False
    if str(data.get("prepayment_generation_started_request_id") or "") == request_id:
        LOGGER.warning("PREPAY_AI_ALREADY_STARTED user=%s request_id=%s", user_id, request_id)
        return False

    decision = can_release_paid_document(
        kind=kind,
        receipt_submitted=True,
        receipt_precheck_passed=True,
        ai_verified=True,
    )
    if not decision.allowed:
        LOGGER.error("PREPAY_AI_RELEASE_BLOCKED user=%s kind=%s reason=%s", user_id, kind, decision.reason)
        return False

    await state.update_data(
        mode="main",
        prepayment_confirmed_request_id=request_id,
        prepayment_confirmed_kind=kind,
        prepayment_confirmed_transaction_id=transaction_id,
        prepayment_generation_started_request_id=request_id,
    )
    await message.answer(
        "✅ KORGAN AI проверил чек. Оплата принята — начинаю подготовку документа."
        if language != KK
        else
        "✅ KORGAN AI чекті тексерді. Төлем қабылданды — құжатты дайындау басталды."
    )
    LOGGER.info(
        "PREPAY_AI_VERIFIED_GENERATION_START user=%s request_id=%s kind=%s transaction=%s",
        user_id,
        request_id,
        kind,
        transaction_id,
    )

    delivery_token = begin_paid_delivery(user_id, kind)
    try:
        await _run_paid_generation(kind, message, state)
    except Exception:
        LOGGER.exception(
            "PREPAY_AI_GENERATION_UNHANDLED user=%s request_id=%s kind=%s transaction=%s",
            user_id,
            request_id,
            kind,
            transaction_id,
        )
        # Payment remains bound to this immutable request and can be retried by
        # support/compatibility flow without asking the client to pay again.
        await state.update_data(prepayment_generation_started_request_id=None)
        await message.answer(
            "Оплата принята, но подготовку документа не удалось завершить. Повторная оплата не нужна; повторите запрос или обратитесь в техподдержку."
            if language != KK
            else
            "Төлем қабылданды, бірақ құжатты дайындау аяқталмады. Қайта төлеу қажет емес; сұрауды қайталаңыз немесе техқолдауға жүгініңіз."
        )
        return False
    finally:
        end_paid_delivery(delivery_token)

    await state.update_data(
        prepayment_generation_started_request_id=None,
        prepayment_consumed_request_id=request_id,
    )
    LOGGER.info(
        "PREPAY_AI_VERIFIED_GENERATION_COMPLETED user=%s request_id=%s kind=%s transaction=%s",
        user_id,
        request_id,
        kind,
        transaction_id,
    )
    return True


@router.callback_query(PaidGenerationFilter())
async def paid_generation_requested(
    callback: CallbackQuery,
    state: FSMContext,
    paid_generation: tuple[int, str, str, str],
) -> None:
    """Compatibility path for generation buttons sent by older deployments."""
    transaction_id, kind, language, signature = paid_generation
    settings = get_settings()
    user_id = callback.from_user.id if callback.from_user else None
    if user_id is None:
        return

    if not verify_paid_generation(settings, signature, user_id, transaction_id, kind, language):
        LOGGER.warning("PREPAY_GENERATE_SIGNATURE_REJECTED user=%s kind=%s", user_id, kind)
        await callback.answer("Некорректный или устаревший запуск.", show_alert=True)
        return
    if callback.message is None:
        await callback.answer("Сообщение недоступно.", show_alert=True)
        return

    await callback.answer("Запускаю документ.")
    await run_ai_verified_prepayment_generation(
        message=callback.message,
        state=state,
        user_id=user_id,
        transaction_id=transaction_id,
        kind=kind,
        language=language,
    )
