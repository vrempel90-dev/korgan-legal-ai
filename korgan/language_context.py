from __future__ import annotations

from contextvars import ContextVar
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.fsm.context import FSMContext
from aiogram.types import TelegramObject

from korgan.i18n import RU, normalize_language

_CURRENT_LANGUAGE: ContextVar[str] = ContextVar("korgan_current_language", default=RU)
_CURRENT_STATE: ContextVar[FSMContext | None] = ContextVar("korgan_current_fsm_state", default=None)


def current_language() -> str:
    return normalize_language(_CURRENT_LANGUAGE.get())


def current_fsm_state() -> FSMContext | None:
    """Return the FSM state bound to the current Telegram update, if any.

    This keeps per-case metadata available to the transport layer without a
    process-global user map. ContextVars are scoped to the current async task,
    so simultaneous chats do not share state.
    """
    return _CURRENT_STATE.get()


class LanguageContextMiddleware(BaseMiddleware):
    """Expose the FSM language/state to renderers and transport per update."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        lang = RU
        state = data.get("state")
        current_state = state if isinstance(state, FSMContext) else None
        if current_state is not None:
            stored = await current_state.get_data()
            lang = normalize_language(stored.get("language", RU))
        language_token = _CURRENT_LANGUAGE.set(lang)
        state_token = _CURRENT_STATE.set(current_state)
        try:
            return await handler(event, data)
        finally:
            _CURRENT_STATE.reset(state_token)
            _CURRENT_LANGUAGE.reset(language_token)
