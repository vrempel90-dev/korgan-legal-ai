from __future__ import annotations

import logging
from typing import Any

from aiogram.methods import SendDocument, SendMessage

from korgan.client_safe_ui import ClientSafeBot, _clean_upload
from korgan.config import get_settings
from korgan.language_context import current_language
from korgan.localized_transport import LocalizedClientSafeBot, _generated_document_kind
from korgan.payment import admin_storage_caption, payment_offer_markup, payment_offer_text

LOGGER = logging.getLogger(__name__)


def install_payment_gate() -> None:
    """Hold generated legal DOCX files until Kaspi payment is confirmed.

    The legal generators are untouched. Only the final Telegram SendDocument is
    intercepted. The withheld DOCX is persisted as a Telegram message in the
    configured administrator chat, so it is not kept only in process RAM.

    Administrators are not exempt when they use the bot as a client. The private
    storage copy is sent through ClientSafeBot.__call__ directly, so it bypasses
    this LocalizedClientSafeBot gate without creating a recursion loop.
    """
    if getattr(LocalizedClientSafeBot, "_kaspi_payment_gate_installed", False):
        return

    original_call = LocalizedClientSafeBot.__call__

    async def payment_aware_call(
        self: LocalizedClientSafeBot,
        method: Any,
        request_timeout: int | None = None,
    ) -> Any:
        settings = get_settings()
        if not isinstance(method, SendDocument) or not settings.payments_enabled:
            return await original_call(self, method, request_timeout=request_timeout)

        kind = _generated_document_kind(method.document)
        if kind is None:
            return await original_call(self, method, request_timeout=request_timeout)

        try:
            user_id = int(method.chat_id)
        except (TypeError, ValueError):
            LOGGER.error("PAYMENT_GATE_NON_PRIVATE_CHAT chat_id=%r", method.chat_id)
            return await original_call(self, method, request_timeout=request_timeout)

        admins = sorted(settings.admin_ids)

        if not settings.kaspi_payment_url.strip() or not admins:
            LOGGER.error(
                "PAYMENT_GATE_CONFIG_ERROR kaspi_url=%s admin_count=%s user=%s",
                bool(settings.kaspi_payment_url.strip()),
                len(admins),
                user_id,
            )
            failure = SendMessage(
                chat_id=method.chat_id,
                text=(
                    "Оплата временно недоступна из-за технической настройки. "
                    "Документ готов, но не выдан. Обратитесь в техподдержку — повторно оплачивать ничего не нужно."
                ),
            )
            return await ClientSafeBot.__call__(self, failure, request_timeout=request_timeout)

        language = current_language()
        admin_id = admins[0]
        stored_method = method.model_copy(
            update={
                "chat_id": admin_id,
                "document": _clean_upload(method.document),
                "caption": admin_storage_caption(user_id, kind, language, settings.document_price_kzt),
                "reply_markup": None,
            }
        )

        try:
            # Bypass LocalizedClientSafeBot.__call__ so the admin storage copy is
            # neither payment-gated nor decorated with the client lawyer CTA.
            stored_message = await ClientSafeBot.__call__(self, stored_method, request_timeout=request_timeout)
        except Exception:
            LOGGER.exception("PAYMENT_GATE_ADMIN_STORAGE_FAILED user=%s kind=%s", user_id, kind)
            failure = SendMessage(
                chat_id=method.chat_id,
                text="Не удалось безопасно зарезервировать готовый документ. Он не выдан и оплата не требуется. Попробуйте позже.",
            )
            return await ClientSafeBot.__call__(self, failure, request_timeout=request_timeout)

        admin_doc_message_id = int(stored_message.message_id)
        offer = SendMessage(
            chat_id=method.chat_id,
            text=payment_offer_text(kind, language, settings.document_price_kzt),
            reply_markup=payment_offer_markup(settings, user_id, admin_doc_message_id, kind, language),
        )
        LOGGER.info(
            "PAYMENT_GATE_HELD user=%s kind=%s admin=%s admin_doc_message_id=%s amount=%s",
            user_id,
            kind,
            admin_id,
            admin_doc_message_id,
            settings.document_price_kzt,
        )
        return await ClientSafeBot.__call__(self, offer, request_timeout=request_timeout)

    LocalizedClientSafeBot.__call__ = payment_aware_call  # type: ignore[method-assign]
    LocalizedClientSafeBot._kaspi_payment_gate_installed = True  # type: ignore[attr-defined]
    LOGGER.info("KORGAN Kaspi payment gate installed")
