from __future__ import annotations

import logging
from functools import wraps
from typing import Any

from korgan.request_scope import active_document_kind, current_request_id

LOGGER = logging.getLogger(__name__)
_INSTALLED = False


def natural_intent_allowed(data: dict) -> bool:
    """Text intent routing is allowed only when no document button owns a request."""
    return active_document_kind(data) is None


async def generator_owns_current_request(state: Any, kind: str) -> bool:
    """Fail closed unless the generator belongs to the current immutable request."""
    return bool(await current_request_id(state, kind))


def _guard_natural_filter(filter_class: type) -> None:
    original = filter_class.__call__
    if getattr(original, "_korgan_document_owner_guard", False):
        return

    @wraps(original)
    async def guarded(self: Any, message: Any, state: Any):
        data = await state.get_data()
        if not natural_intent_allowed(data):
            return False
        return await original(self, message, state)

    guarded._korgan_document_owner_guard = True  # type: ignore[attr-defined]
    filter_class.__call__ = guarded


def _guard_generator(module: Any, attribute: str, kind: str) -> None:
    original = getattr(module, attribute)
    if getattr(original, "_korgan_document_owner_guard", False):
        return

    @wraps(original)
    async def guarded(message: Any, state: Any, *args: Any, **kwargs: Any):
        if not await generator_owns_current_request(state, kind):
            data = await state.get_data()
            LOGGER.error(
                "CROSS_DOCUMENT_GENERATOR_BLOCKED target=%s active_kind=%s request_id=%s mode=%s",
                kind,
                data.get("request_kind"),
                data.get("request_id"),
                data.get("mode"),
            )
            return None
        return await original(message, state, *args, **kwargs)

    guarded._korgan_document_owner_guard = True  # type: ignore[attr-defined]
    setattr(module, attribute, guarded)


def install_document_generator_ownership_guard() -> None:
    """Make a selected document request authoritative down to generator entry.

    The UI/router lock is not enough by itself: legacy natural-language intent
    filters can otherwise start another document workflow when case facts contain
    words such as «претензия», «договор» or «отзыв». This guard adds two fail-closed
    layers without changing legal prompts or document builders:

    1. Natural-intent filters cannot start any document while a button-created
       request is active.
    2. Every generator checks that its own kind still owns the current request
       before research, drafting or DOCX construction can begin.
    """
    global _INSTALLED
    if _INSTALLED:
        return

    from korgan import pretrial_response_runtime, pretrial_runtime
    from korgan import universal_claim_runtime, universal_document_runtime

    for filter_class in (
        pretrial_runtime._Intent,
        pretrial_response_runtime._Intent,
        universal_claim_runtime._ClaimIntent,
        universal_document_runtime.ContractRequestFilter,
        universal_document_runtime.ResponseRequestFilter,
    ):
        _guard_natural_filter(filter_class)

    for module, attribute, kind in (
        (universal_claim_runtime, "_generate_now", "claim"),
        (pretrial_runtime, "_generate", "pretrial"),
        (pretrial_response_runtime, "_generate", "pretrial_response"),
        (universal_document_runtime, "_send_response", "response"),
        (universal_document_runtime, "_send_contract", "contract"),
    ):
        _guard_generator(module, attribute, kind)

    _INSTALLED = True
    LOGGER.info("KORGAN hard document-generator ownership guard installed")
