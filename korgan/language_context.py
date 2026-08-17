from __future__ import annotations

from contextvars import ContextVar
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.fsm.context import FSMContext
from aiogram.types import TelegramObject

from korgan.i18n import RU, normalize_language

_CURRENT_LANGUAGE: ContextVar[str] = ContextVar("korgan_current_language", default=RU)


def current_language() -> str:
    return normalize_language(_CURRENT_LANGUAGE.get())


class LanguageContextMiddleware(BaseMiddleware):
    """Expose the FSM language to renderers/transport without global user state."""

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
            return await handler(event, data)
        finally:
            _CURRENT_LANGUAGE.reset(token)
