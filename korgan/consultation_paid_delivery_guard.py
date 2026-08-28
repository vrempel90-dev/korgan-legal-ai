from __future__ import annotations

import logging

from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from korgan import consultation_quota as store
from korgan import consultation_quota_runtime as runtime
from korgan.payment_operation_lock import payment_operation_lock

LOGGER = logging.getLogger(__name__)
_INSTALLED = False
_ORIGINAL_DELIVER = runtime._deliver_paid_order


async def _guarded_deliver_paid_order(
    message: Message,
    state: FSMContext,
    order: store.ConsultationOrder,
) -> None:
    async with payment_operation_lock(
        store._require_pool(),
        "consultation-delivery",
        order.id,
    ):
        fresh = await store.get_consultation_order(order.id, order.user_id)
        if fresh is None:
            await message.answer("Платёжный запрос не найден.")
            return
        if fresh.status == "consumed":
            # Idempotent second tap: acknowledge without regenerating/delivering.
            await message.answer("Эта оплаченная консультация уже была выдана. Повторная оплата не нужна.")
            return
        if fresh.status != "paid":
            await message.answer("Оплата этой консультации ещё не подтверждена.")
            return
        await _ORIGINAL_DELIVER(message, state, fresh)


def install_consultation_paid_delivery_guard() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    runtime._deliver_paid_order = _guarded_deliver_paid_order
    _INSTALLED = True
    LOGGER.info("Installed cross-process paid consultation delivery idempotency guard")
