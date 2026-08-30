from __future__ import annotations

import os
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from korgan.admin import is_admin
from korgan.config import get_settings

_TRUTHY = {"1", "true", "yes", "on"}


def shadow_mode_enabled() -> bool:
    return os.getenv("TELEGRAM_ADMIN_ONLY", "").strip().lower() in _TRUTHY


def _message_allowed(message: Message) -> bool:
    text = str(message.text or "").strip().lower()
    return text == "/admin" or text.startswith("/admin@")


def _callback_allowed(callback: CallbackQuery) -> bool:
    data = str(callback.data or "")
    return data.startswith("admin:") or data.startswith("adminpay:")


class TelegramShadowGuard(BaseMiddleware):
    """Keep the legacy Telegram AI runtime mounted but unreachable to clients.

    MiniApp remains the customer product. When TELEGRAM_ADMIN_ONLY=1, customer
    Telegram messages/callbacks are silently dropped before they reach any AI,
    document or consultation router. Only the configured administrator can use
    /admin and administrator callbacks. This avoids removing tested legacy code.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not shadow_mode_enabled():
            return await handler(event, data)

        user = getattr(event, "from_user", None)
        user_id = getattr(user, "id", None)
        if not is_admin(user_id, get_settings()):
            return None

        if isinstance(event, Message):
            if not _message_allowed(event):
                return None
        elif isinstance(event, CallbackQuery):
            if not _callback_allowed(event):
                return None
        else:
            return None

        return await handler(event, data)
