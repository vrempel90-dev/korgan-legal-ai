from __future__ import annotations

import logging

from korgan import document_quality as _dq
from korgan import senior_claim_preflight as _sp
from korgan.claim_quality_hotfix import FILING_ACTION_PREFIX, ProductionClaimService
from korgan.fast_v2_production_legal import _deterministic_pre_qa
from korgan.late_interest_hotfix import _apply_verified_article_353, _today_kz
from korgan.legal_types import ClaimDraft, LegalResearch, VerificationStatus
from korgan.professional_claim_finalizer import finalize_professional_claim

LOGGER = logging.getLogger(__name__)


class FinalizedProductionClaimService(ProductionClaimService):
    """Current production quality core plus a zero-call claim finalizer.

    `claim_quality_hotfix` remains authoritative for separating filing-only
    prerequisites from substantive legal quality. This adapter runs after its
    fast research/draft/optional-repair path and removes the remaining model
    discretion from court selection, legal-basis transfer, relief cleanup and
    price/state-duty synchronization. No additional model or web call is added.
    """

    async def draft_claim(
        self,
        case_context: str,
        research: LegalResearch,
        language: str = "ru",
    ) -> ClaimDraft:
        draft = await super().draft_claim(case_context, research, language=language)

        # Enforce filing invariants in code, then let the existing deterministic
        # arithmetic/cleanup run on the corrected relief set.
        finalize_professional_claim(case_context, research, draft)
        _deterministic_pre_qa(case_context, research, draft)
        _apply_verified_article_353(case_context, research, draft, filing_date=_today_kz())

        # Article 353 or deterministic cleanup may alter monetary relief. Finish
        # once more and recompute price/state duty without another model call.
        finalize_professional_claim(case_context, research, draft)
        _deterministic_pre_qa(case_context, research, draft)

        # Read through the modules because claim_quality_hotfix monkeypatches
        # these functions at startup; bound imports would bypass the active policy.
        deterministic = _sp.deterministic_claim_preflight(case_context, research, draft)
        quality = _dq.assess_document_quality("claim", case_context, research, draft)
        LOGGER.info(
            "FINALIZED_PROFESSIONAL_CLAIM score=%.1f ready=%s deterministic=%s blockers=%s",
            quality.score,
            quality.ready,
            deterministic[:6],
            quality.hard_blockers[:6],
        )

        filing = [
            str(note)
            for note in draft.verification_notes
            if str(note).startswith(FILING_ACTION_PREFIX)
        ]
        nonfiling = [
            str(note)
            for note in draft.verification_notes
            if not str(note).startswith(FILING_ACTION_PREFIX)
            and not str(note).startswith("SENIOR_PREFLIGHT_SCORE:")
        ]

        if quality.ready and not deterministic and not nonfiling:
            if filing:
                # Filing-only prerequisites stay visible without pretending the
                # substantive legal work failed quality review.
                draft.status = VerificationStatus.NEEDS_VERIFICATION
                draft.verification_notes = filing
            else:
                draft.status = VerificationStatus.VERIFIED
                draft.verification_notes.clear()
            return draft

        draft.status = VerificationStatus.NEEDS_VERIFICATION
        remaining = list(dict.fromkeys([*deterministic, *quality.hard_blockers]))
        final_score = min(quality.score, 6.9 if deterministic else quality.score)
        score_note = (
            f"SENIOR_PREFLIGHT_SCORE: {final_score:.1f}/10 — "
            + ("; ".join(remaining[:6]) or "не достигнут порог 8.5")
        )
        draft.verification_notes = list(dict.fromkeys([*filing, *nonfiling, score_note]))
        return draft
