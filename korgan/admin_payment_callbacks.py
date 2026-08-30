from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery

from korgan.admin import is_admin
from korgan.admin_payment_store import decide_admin_payment_order, get_admin_payment_order
from korgan.config import get_settings

LOGGER = logging.getLogger(__name__)
router = Router(name="admin_payment_callbacks")


def _parse(data: str) -> tuple[bool, int] | None:
    parts = str(data or "").split(":")
    if len(parts) != 3 or parts[0] != "adminpay" or parts[1] not in {"approve", "reject"}:
        return None
    try:
        order_id = int(parts[2])
    except ValueError:
        return None
    if order_id <= 0:
        return None
    return parts[1] == "approve", order_id


@router.callback_query(F.data.startswith("adminpay:"))
async def admin_payment_callback(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id if callback.from_user else None
    if not is_admin(user_id, get_settings()):
        LOGGER.warning("ADMIN_PAYMENT_DENIED telegram_user_id=%s data=%s", user_id, callback.data)
        await callback.answer("Недостаточно прав.", show_alert=True)
        return

    parsed = _parse(str(callback.data or ""))
    if parsed is None or user_id is None:
        await callback.answer("Некорректная команда.", show_alert=True)
        return
    approved, order_id = parsed

    try:
        order = await get_admin_payment_order(order_id)
    except Exception:
        LOGGER.exception("ADMIN_PAYMENT_LOOKUP_FAILED order_id=%s", order_id)
        await callback.answer("Не удалось прочитать статус заказа.", show_alert=True)
        return

    if order is None:
        await callback.answer("Заказ не найден.", show_alert=True)
        return

    if order.status != "awaiting_admin":
        if approved and order.status in {"approved", "consumed"}:
            await callback.answer("Оплата уже подтверждена.")
        elif not approved and order.status == "pending_receipt":
            await callback.answer("Чек уже отклонён; ожидается новый чек.")
        else:
            await callback.answer(f"Текущий статус заказа: {order.status}.", show_alert=True)
        return

    try:
        changed = await decide_admin_payment_order(
            order_id,
            approved=approved,
            admin_id=user_id,
        )
    except Exception:
        LOGGER.exception("ADMIN_PAYMENT_DECISION_FAILED order_id=%s admin_id=%s", order_id, user_id)
        await callback.answer("Не удалось сохранить решение.", show_alert=True)
        return

    if not changed:
        await callback.answer("Статус уже изменён другим действием.", show_alert=True)
        return

    status_text = "✅ ОПЛАТА ПОДТВЕРЖДЕНА" if approved else "❌ ЧЕК ОТКЛОНЁН"
    answer_text = (
        "Оплата подтверждена. Клиент может продолжить подготовку документа."
        if approved
        else "Чек отклонён. Клиент сможет загрузить другой чек без нового заказа."
    )
    LOGGER.info(
        "ADMIN_PAYMENT_DECISION telegram_user_id=%s order_id=%s approved=%s",
        user_id,
        order_id,
        approved,
    )
    await callback.answer(answer_text)

    if callback.message:
        old_caption = (callback.message.caption or "").strip()
        suffix = f"\n\n{status_text}\nАдминистратор: {user_id}"
        room = max(0, 1024 - len(suffix))
        new_caption = old_caption[:room] + suffix
        try:
            await callback.message.edit_caption(caption=new_caption, reply_markup=None)
        except Exception:
            LOGGER.exception("ADMIN_PAYMENT_MESSAGE_EDIT_FAILED order_id=%s", order_id)
