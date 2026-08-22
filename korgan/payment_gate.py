from __future__ import annotations

import logging
from typing import Any, Iterable

from aiogram.methods import SendDocument, SendMessage

from korgan.client_safe_ui import ClientSafeBot, _clean_upload
from korgan.config import get_settings
from korgan.language_context import current_language
from korgan.localized_transport import LocalizedClientSafeBot, _generated_document_kind
from korgan.payment import admin_storage_caption, payment_offer_markup, payment_offer_text
from korgan.prepayment_gate import is_paid_delivery_authorized

LOGGER = logging.getLogger(__name__)


def _select_storage_admin(admin_ids: Iterable[int], user_id: int) -> int | None:
    """Return a deterministic admin chat that is not the paying client.

    The held Word document is a private storage copy. Sending that copy to the
    payer — even when the payer is also an administrator/tester — would expose
    the file before payment and defeat the gate. No safe admin means fail closed.
    """
    return next((admin_id for admin_id in sorted(set(admin_ids)) if admin_id != user_id), None)


def install_payment_gate() -> None:
    """Fail closed for every generated legal DOCX.

    New requests are paid before generation. Their DOCX is allowed through only
    while an admin-confirmed paid-generation context matches both client and kind.
    Any generated document outside that narrow context falls back to the legacy
    hold flow, which stores it privately and asks for payment instead of exposing
    a free Word file. Positive-id legacy payment cards therefore remain usable.
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
            LOGGER.error("PAYMENT_GATE_INVALID_CLIENT_CHAT chat_id=%r kind=%s", method.chat_id, kind)
            failure = SendMessage(
                chat_id=method.chat_id,
                text=(
                    "Не удалось открыть защищённую выдачу документа. Документ не выдан. "
                    "Повторите запрос позже или обратитесь в техподдержку."
                ),
            )
            return await ClientSafeBot.__call__(self, failure, request_timeout=request_timeout)

        # This context is set only after receipt pre-check + explicit admin
        # confirmation, and only around one paid generation task.
        if is_paid_delivery_authorized(user_id, kind):
            LOGGER.info("PREPAID_DOCUMENT_DELIVERY user=%s kind=%s", user_id, kind)
            return await original_call(self, method, request_timeout=request_timeout)

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
        LOGGER.warning(
            "PAYMENT_GATE_FALLBACK_HELD user=%s kind=%s admin=%s admin_doc_message_id=%s amount=%s",
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
        """Route generated DOCX convenience sends through the same fail-closed gate."""
        settings = get_settings()
        kind = _generated_document_kind(document)
        if kind is None or not settings.payments_enabled:
            return await original_send_document(self, chat_id, document, *args, **kwargs)

        try:
            user_id = int(chat_id)
        except (TypeError, ValueError):
            user_id = 0
        if user_id and is_paid_delivery_authorized(user_id, kind):
            LOGGER.info("PREPAID_DOCUMENT_SEND user=%s kind=%s", user_id, kind)
            return await original_send_document(self, chat_id, document, *args, **kwargs)

        if args:
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
    LOGGER.info("KORGAN Kaspi payment gate installed (prepay-aware fallback)")
