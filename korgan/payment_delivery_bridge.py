from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram.types import Message

from korgan.localized_transport import _generated_document_kind

LOGGER = logging.getLogger(__name__)
_INSTALLED = False
_ORIGINAL_ANSWER_DOCUMENT: Callable[..., Awaitable[Any]] | None = None


def install_payment_delivery_bridge() -> None:
    """Force generated KORGAN DOCX shortcut sends through Bot.send_document.

    Aiogram Message.answer_document() may execute its SendDocument shortcut without
    traversing the LocalizedClientSafeBot.send_document override used by the
    Kaspi payment gate.  Only known generated KORGAN document filenames are
    redirected here.  All other documents keep aiogram's original behavior.
    """
    global _INSTALLED, _ORIGINAL_ANSWER_DOCUMENT
    if _INSTALLED:
        return

    original = Message.answer_document
    _ORIGINAL_ANSWER_DOCUMENT = original

    async def payment_aware_answer_document(
        self: Message,
        document: Any,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        kind = _generated_document_kind(document)
        if kind is None:
            return await original(self, document, *args, **kwargs)

        bot = self.bot
        if bot is None:
            LOGGER.error("PAYMENT_DELIVERY_NO_BOT kind=%s chat=%s", kind, getattr(self.chat, "id", None))
            return await original(self, document, *args, **kwargs)

        LOGGER.info("PAYMENT_DELIVERY_ROUTE_GATE user=%s kind=%s", self.chat.id, kind)
        return await bot.send_document(
            chat_id=self.chat.id,
            document=document,
            *args,
            **kwargs,
        )

    Message.answer_document = payment_aware_answer_document  # type: ignore[method-assign]
    _INSTALLED = True
    LOGGER.info("KORGAN generated DOCX payment delivery bridge installed")
