from __future__ import annotations

import logging
from typing import Any, Iterable

from aiogram.methods import SendDocument, SendMessage

from korgan.client_safe_ui import ClientSafeBot, _clean_upload
from korgan.config import get_settings
from korgan.language_context import current_language
from korgan.localized_transport import LocalizedClientSafeBot, _generated_document_kind
from korgan.payment import admin_storage_caption, payment_offer_markup, payment_offer_text

LOGGER = logging.getLogger(__name__)


def _select_storage_admin(admin_ids: Iterable[int], user_id: int) -> int | None:
    """Return a deterministic admin chat that is not the paying client.

    The held Word document is a private storage copy. Sending that copy to the
    payer — even when the payer is also an administrator/tester — would expose
    the file before payment and defeat the gate. No safe admin means fail closed.
    """
    return next((admin_id for admin_id in sorted(set(admin_ids)) if admin_id != user_id), None)


def install_payment_gate() -> None:
    """Hold generated legal DOCX files until Kaspi payment is confirmed.

    Aiogram can deliver documents through either ``Bot.__call__(SendDocument)``
    or the convenience ``send_document()`` method depending on the caller/version.
    KORGAN must gate both paths. The withheld DOCX is persisted as a Telegram
    message in a configured administrator chat that is different from the payer,
    and only the payment offer is sent to the client until the receipt is accepted.

    Administrators are not exempt when they use the bot as a client. The private
    storage copy is sent through ClientSafeBot.__call__ directly, so it bypasses
    this LocalizedClientSafeBot gate without creating a recursion loop.
    """
    if getattr(LocalizedClientSafeBot, "_kaspi_payment_gate_installed", False):
        return

    original_call = LocalizedClientSafeBot.__call__
    original_send_document = LocalizedClientSafeBot.send_document

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
            # Paid generated documents must fail closed. An unexpected chat id
            # must never become a bypass that sends the Word file for free.
            LOGGER.error("PAYMENT_GATE_INVALID_CLIENT_CHAT chat_id=%r kind=%s", method.chat_id, kind)
            failure = SendMessage(
                chat_id=method.chat_id,
                text=(
                    "Не удалось открыть защищённую выдачу документа. Документ не выдан. "
                    "Повторите запрос позже или обратитесь в техподдержку."
                ),
            )
            return await ClientSafeBot.__call__(self, failure, request_timeout=request_timeout)

        admins = sorted(settings.admin_ids)
        storage_admin_id = _select_storage_admin(admins, user_id)
        if not settings.kaspi_payment_url.strip() or storage_admin_id is None:
            LOGGER.error(
                "PAYMENT_GATE_CONFIG_ERROR kaspi_url=%s admin_count=%s safe_storage=%s user=%s",
                bool(settings.kaspi_payment_url.strip()),
                len(admins),
                storage_admin_id is not None,
                user_id,
            )
            failure = SendMessage(
                chat_id=method.chat_id,
                text=(
                    "Оплата временно недоступна из-за технической настройки. "
                    "Документ готов, но не выдан. Оплата не требуется. Обратитесь в техподдержку."
                ),
            )
            return await ClientSafeBot.__call__(self, failure, request_timeout=request_timeout)

        language = current_language()
        stored_method = method.model_copy(
            update={
                "chat_id": storage_admin_id,
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
            storage_admin_id,
            admin_doc_message_id,
            settings.document_price_kzt,
        )
        return await ClientSafeBot.__call__(self, offer, request_timeout=request_timeout)

    async def payment_aware_send_document(
        self: LocalizedClientSafeBot,
        chat_id: Any,
        document: Any,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Route generated DOCX convenience sends through the same payment gate."""
        settings = get_settings()
        kind = _generated_document_kind(document)
        if kind is None or not settings.payments_enabled:
            return await original_send_document(self, chat_id, document, *args, **kwargs)

        if args:
            # Generated KORGAN sends use keyword options. Fail closed instead of
            # silently bypassing payment if a future caller adds positional data.
            LOGGER.error("PAYMENT_GATE_UNSUPPORTED_POSITIONAL_SEND user=%r kind=%s", chat_id, kind)
            failure = SendMessage(
                chat_id=chat_id,
                text="Документ готов, но платёжный шлюз не смог безопасно подготовить выдачу. Обратитесь в техподдержку — документ не выдан.",
            )
            return await ClientSafeBot.__call__(self, failure)

        request_timeout = kwargs.pop("request_timeout", None)
        method = SendDocument(chat_id=chat_id, document=document, **kwargs)
        return await payment_aware_call(self, method, request_timeout=request_timeout)

    LocalizedClientSafeBot.__call__ = payment_aware_call  # type: ignore[method-assign]
    LocalizedClientSafeBot.send_document = payment_aware_send_document  # type: ignore[method-assign]
    LocalizedClientSafeBot._kaspi_payment_gate_installed = True  # type: ignore[attr-defined]
    LOGGER.info("KORGAN Kaspi payment gate installed")
