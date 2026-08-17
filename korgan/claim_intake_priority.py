from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import BaseFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from korgan import bot as base_bot
from korgan.i18n import BUTTONS, KK, RU

router = Router(name="korgan-claim-intake-priority")

_NAV_TEXTS = set(BUTTONS[RU].values()) | set(BUTTONS[KK].values())
_ACTIVE_CLAIM_MODES = {"claim_details", "verification_gate"}


class ActiveClaimReplyFilter(BaseFilter):
    """Keep replies inside an active claim dialogue before generic document routers."""

    async def __call__(self, message: Message, state: FSMContext) -> bool:
        text = (message.text or "").strip()
        if not text or text.startswith("/") or text in _NAV_TEXTS:
            return False
        data = await state.get_data()
        return data.get("mode") in _ACTIVE_CLAIM_MODES


class ClaimButtonWhileWaitingFilter(BaseFilter):
    """Do not count repeated claim-button clicks as failed field answers."""

    async def __call__(self, callback: CallbackQuery, state: FSMContext) -> bool:
        data = await state.get_data()
        return data.get("mode") == "claim_details"


@router.message(ActiveClaimReplyFilter())
async def active_claim_reply(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    if data.get("mode") == "verification_gate":
        await base_bot._handle_verification_gate_reply(message, state, data)
        return
    await base_bot._handle_missing_field_answer(message, state, data)


@router.callback_query(F.data == "doc:claim", ClaimButtonWhileWaitingFilter())
async def claim_button_while_waiting(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message is None:
        return
    data = await state.get_data()
    pending = list(data.get("pending_fields", []) or [])
    items = "\n".join(f"• {item}" for item in pending[:8])
    await callback.message.answer(
        "Иск уже находится на этапе уточнения данных. Повторно запускать его не нужно.\n\n"
        + (f"Сейчас нужны:\n{items}\n\n" if items else "")
        + "Пришлите недостающие сведения одним сообщением — я сохраню их и продолжу подготовку автоматически."
    )
