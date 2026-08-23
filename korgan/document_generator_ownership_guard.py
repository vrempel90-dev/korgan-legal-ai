from __future__ import annotations

import logging
from contextvars import ContextVar
from functools import wraps
from typing import Any

from korgan.request_scope import active_document_kind, current_request_id, request_is_current

LOGGER = logging.getLogger(__name__)
_INSTALLED = False
_ACTIVE_GENERATOR_OWNER: ContextVar[tuple[Any, str, str] | None] = ContextVar(
    "korgan_active_document_generator_owner",
    default=None,
)


class StaleDocumentRequest(RuntimeError):
    """Raised when an async generation task no longer owns the active request."""


def natural_intent_allowed(data: dict) -> bool:
    """Text intent routing is allowed only when no document button owns a request."""
    return active_document_kind(data) is None


async def generator_owns_current_request(state: Any, kind: str) -> bool:
    """Fail closed unless the generator belongs to the current immutable request."""
    return bool(await current_request_id(state, kind))


async def active_generation_still_owned(expected_kind: str | None = None) -> bool:
    """Check ownership captured at generator entry against the live FSM request."""
    owner = _ACTIVE_GENERATOR_OWNER.get()
    if owner is None:
        # Direct service unit tests and offline tools do not have Telegram FSM
        # ownership. Production transport always enters through _guard_generator.
        return True
    state, kind, request_id = owner
    if expected_kind is not None and kind != expected_kind:
        return False
    return await request_is_current(state, request_id, kind)


async def _require_active_generation(expected_kind: str | None = None) -> None:
    if await active_generation_still_owned(expected_kind):
        return
    owner = _ACTIVE_GENERATOR_OWNER.get()
    kind = owner[1] if owner is not None else expected_kind
    request_id = owner[2] if owner is not None else ""
    LOGGER.info(
        "STALE_DOCUMENT_GENERATION_ABORT kind=%s request_id=%s stage=before_openai_call",
        kind,
        request_id,
    )
    raise StaleDocumentRequest(f"stale document request: {kind or 'unknown'}")


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
        request_id = await current_request_id(state, kind)
        if not request_id:
            data = await state.get_data()
            LOGGER.error(
                "CROSS_DOCUMENT_GENERATOR_BLOCKED target=%s active_kind=%s request_id=%s mode=%s",
                kind,
                data.get("request_kind"),
                data.get("request_id"),
                data.get("mode"),
            )
            return None

        token = _ACTIVE_GENERATOR_OWNER.set((state, kind, request_id))
        try:
            return await original(message, state, *args, **kwargs)
        finally:
            _ACTIVE_GENERATOR_OWNER.reset(token)

    guarded._korgan_document_owner_guard = True  # type: ignore[attr-defined]
    setattr(module, attribute, guarded)


def _guard_service_draft(service_class: type, attribute: str, kind: str) -> None:
    """Re-check ownership after research and before a draft OpenAI call starts."""
    original = getattr(service_class, attribute)
    if getattr(original, "_korgan_stale_request_guard", False):
        return

    @wraps(original)
    async def guarded(self: Any, *args: Any, **kwargs: Any):
        await _require_active_generation(kind)
        return await original(self, *args, **kwargs)

    guarded._korgan_stale_request_guard = True  # type: ignore[attr-defined]
    setattr(service_class, attribute, guarded)


def _guard_quality_repair(service_class: type) -> None:
    """Never spend a repair OpenAI call after the client switched requests."""
    original = service_class._quality_repair
    if getattr(original, "_korgan_stale_request_guard", False):
        return

    @wraps(original)
    async def guarded(self: Any, *args: Any, **kwargs: Any):
        await _require_active_generation()
        return await original(self, *args, **kwargs)

    guarded._korgan_stale_request_guard = True  # type: ignore[attr-defined]
    service_class._quality_repair = guarded


def install_document_generator_ownership_guard() -> None:
    """Make a selected document request authoritative through every AI stage.

    The UI/router lock is not enough by itself: legacy natural-language intent
    filters can otherwise start another document workflow when case facts contain
    words such as «претензия», «договор» or «отзыв». The guard now protects three
    levels without changing legal prompts or document builders:

    1. Natural-intent filters cannot start another document while a request owns
       the section.
    2. Every top-level generator captures immutable request_id + request_kind.
    3. Draft and bounded-repair model calls re-check that captured owner. If the
       client switched documents while research/drafting was in flight, no next
       OpenAI call starts and the stale transport result is never delivered.
    """
    global _INSTALLED
    if _INSTALLED:
        return

    from korgan import pretrial_response_runtime, pretrial_runtime
    from korgan import universal_claim_runtime, universal_document_runtime
    from korgan.pretrial import PretrialProductionService
    from korgan.pretrial_response import PretrialResponseProductionService
    from korgan.stable_legal_release import StableLegalProductionService
    from korgan.universal_quality_service import UniversalQualityProductionService

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

    # These wrappers run after the universal quality guard has installed its
    # final production methods, so ownership remains outermost and cannot be
    # swallowed by the PRELIMINARY fail-open repair fallback.
    for service_class, attribute, kind in (
        (StableLegalProductionService, "draft_claim", "claim"),
        (UniversalQualityProductionService, "draft_contract", "contract"),
        (UniversalQualityProductionService, "draft_response_to_claim", "response"),
        (PretrialProductionService, "draft_pretrial", "pretrial"),
        (PretrialResponseProductionService, "draft_pretrial_response", "pretrial_response"),
    ):
        _guard_service_draft(service_class, attribute, kind)

    _guard_quality_repair(UniversalQualityProductionService)

    _INSTALLED = True
    LOGGER.info(
        "KORGAN hard document-generator ownership guard installed: request owner rechecked before draft/repair OpenAI calls"
    )
