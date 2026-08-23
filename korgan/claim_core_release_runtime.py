from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from korgan.claim_core_release import core_claim_release_blockers
from korgan.legal_types import ClaimDraft, LegalResearch, VerificationStatus
from korgan.request_scope import request_is_current

LOGGER = logging.getLogger(__name__)


def _blocked_text(language: str) -> str:
    """Legacy copy retained for compatibility with callers/tests.

    Core completeness defects no longer stop Word export at this wrapper. The
    installed production sender is responsible for marking such documents as
    preliminary while citation/integrity failures remain fail-closed.
    """
    if language == "kk":
        return (
            "Иск Word ретінде әлі шығарылмады: сотқа берілетін құжатта орындалатын талаптар "
            "және ресми дереккөзбен расталған материалдық-құқықтық негіз міндетті түрде болуы керек. "
            "KORGAN тексеруді аяқтамайынша толық емес талап қою арызын дайын құжат ретінде бермейді."
        )
    return (
        "Иск пока не выпущен в Word: в судебном документе обязательно должны быть "
        "исполнимая просительная часть и подтверждённое официальным источником "
        "материально-правовое основание. KORGAN не выдаёт неполный иск как готовый документ."
    )


async def send_with_core_release_guard(
    original_send: Callable[..., Awaitable[Any]],
    message: Any,
    state: Any,
    *,
    context: str,
    research: LegalResearch,
    draft: ClaimDraft,
    request_id: str,
) -> Any:
    """Downgrade core-incomplete claims to preliminary instead of dropping Word.

    The regression fixed here was introduced when this final wrapper turned
    missing executable relief/source-bound material law into an unconditional
    transport stop. The sender underneath already has a PRELIMINARY path and
    still fail-closes on damaged text or unsafe citations. Keep the diagnostic
    core gate, but let that established sender deliver a clearly non-ready draft.
    """
    if not await request_is_current(state, request_id, "claim"):
        LOGGER.info("STALE_DOCUMENT_SUPPRESSED kind=claim request_id=%s", request_id)
        return None

    blockers = core_claim_release_blockers(research, draft)
    if blockers:
        draft.status = VerificationStatus.NEEDS_VERIFICATION
        LOGGER.warning(
            "PRODUCTION_CLAIM_CORE_PRELIMINARY request_id=%s blockers=%s",
            request_id,
            blockers[:4],
        )

    if not await request_is_current(state, request_id, "claim"):
        LOGGER.info("STALE_DOCUMENT_SUPPRESSED kind=claim request_id=%s", request_id)
        return None

    return await original_send(
        message,
        state,
        context=context,
        research=research,
        draft=draft,
        request_id=request_id,
    )


def install_claim_core_release_guard() -> None:
    """Wrap the final installed claim sender with a core-completeness downgrade."""
    from korgan import universal_claim_runtime as runtime

    current = runtime._send_claim
    if getattr(current, "_korgan_claim_core_release_guard", False):
        return

    async def guarded_send(
        message: Any,
        state: Any,
        *,
        context: str,
        research: LegalResearch,
        draft: ClaimDraft,
        request_id: str,
    ) -> Any:
        # Keep the stale-request release guard on the actual installed sender as
        # well as in the shared helper. Besides making the safety invariant
        # locally auditable, this prevents any future refactor from delegating a
        # stale request into the helper accidentally.
        if not await request_is_current(state, request_id, "claim"):
            LOGGER.info("STALE_DOCUMENT_SUPPRESSED kind=claim request_id=%s", request_id)
            return None
        return await send_with_core_release_guard(
            current,
            message,
            state,
            context=context,
            research=research,
            draft=draft,
            request_id=request_id,
        )

    guarded_send._korgan_claim_core_release_guard = True  # type: ignore[attr-defined]
    guarded_send._korgan_claim_core_release_original = current  # type: ignore[attr-defined]
    runtime._send_claim = guarded_send
    LOGGER.info("Installed final production claim core release guard")
