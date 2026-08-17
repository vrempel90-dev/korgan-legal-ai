from __future__ import annotations

from contextvars import ContextVar
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, TelegramObject

from korgan.i18n import BUTTONS, KK, RU, normalize_language

_CURRENT_LANGUAGE: ContextVar[str] = ContextVar("korgan_current_language", default=RU)
_KK_TO_RU_BUTTON = {value: BUTTONS[RU][key] for key, value in BUTTONS[KK].items()}


def current_language() -> str:
    return normalize_language(_CURRENT_LANGUAGE.get())


class LanguageContextMiddleware(BaseMiddleware):
    """Expose session language and map KK menu input onto the proven RU handlers."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        lang = RU
        state = data.get("state")
        if isinstance(state, FSMContext):
            stored = await state.get_data()
            lang = normalize_language(stored.get("language", RU))
        token = _CURRENT_LANGUAGE.set(lang)
        try:
            routed_event: TelegramObject = event
            if lang == KK and isinstance(event, Message) and event.text in _KK_TO_RU_BUTTON:
                routed_event = event.model_copy(update={"text": _KK_TO_RU_BUTTON[event.text]})
            return await handler(routed_event, data)
        finally:
            _CURRENT_LANGUAGE.reset(token)
