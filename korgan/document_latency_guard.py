from __future__ import annotations

import logging

from korgan.document_quality import assess_document_quality
from korgan.legal_types import VerificationStatus
from korgan.universal_quality_service import UniversalQualityProductionService, _quality_note

LOGGER = logging.getLogger(__name__)
_PATCHED = False


async def _latency_bounded_draft_contract(
    self: UniversalQualityProductionService,
    case_context: str,
    research,
    language: str = "ru",
):
    """Keep the proven contract QA loop while preventing a second outer repair.

    The next production layer already performs the complete contract sequence:
    source-bound drafting, independent AI validation, one bounded repair when
    required, and validation of the repaired result. Running
    ``UniversalQualityProductionService._quality_repair`` afterwards repeats the
    same editing job and can add another long OpenAI request without adding an
    independent safety boundary.

    We still run the shared deterministic >=8.5 quality gate here. It can only
    downgrade the returned draft and surface remaining issues; it never upgrades
    or bypasses the lower production QA result.
    """
    draft = await super(UniversalQualityProductionService, self).draft_contract(
        case_context,
        research,
        language=language,
    )

    quality = assess_document_quality("contract", case_context, research, draft)
    LOGGER.info(
        "DOCUMENT_QUALITY kind=contract stage=latency-bounded-final score=%.1f ready=%s blockers=%s",
        quality.score,
        quality.ready,
        quality.hard_blockers[:6],
    )
    if not quality.ready:
        draft.status = VerificationStatus.NEEDS_VERIFICATION
        note = _quality_note(quality.score, quality.repair_issues())
        if note not in draft.verification_notes:
            draft.verification_notes.append(note)
    return draft


def install_document_latency_guard() -> None:
    """Install the contract-only duplicate-repair guard once per process."""
    global _PATCHED
    if _PATCHED:
        return
    UniversalQualityProductionService.draft_contract = _latency_bounded_draft_contract
    _PATCHED = True
    LOGGER.info("Installed KORGAN latency guard: duplicate outer contract repair disabled")
