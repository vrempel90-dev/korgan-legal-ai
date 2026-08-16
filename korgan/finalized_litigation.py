from __future__ import annotations

import logging

from korgan.document_quality import assess_document_quality
from korgan.fast_professional_litigation import FastProfessionalLitigationService
from korgan.fast_v2_production_legal import _deterministic_pre_qa
from korgan.late_interest_hotfix import _apply_verified_article_353, _today_kz
from korgan.legal_types import ClaimDraft, LegalResearch, VerificationStatus
from korgan.professional_claim_finalizer import finalize_professional_claim
from korgan.senior_claim_preflight import deterministic_claim_preflight

LOGGER = logging.getLogger(__name__)


class FinalizedProfessionalLitigationService(FastProfessionalLitigationService):
    """Professional release adapter with zero additional model/web calls.

    The fast service still owns research, drafting and at most one repair. This
    adapter then enforces source-bound court selection, legal-basis reconstruction,
    fact-locked remedies and recalculation entirely in code before final scoring.
    """

    async def draft_claim(
        self,
        case_context: str,
        research: LegalResearch,
        language: str = "ru",
    ) -> ClaimDraft:
        draft = await super().draft_claim(case_context, research, language=language)

        # Replace model discretion with deterministic filing invariants.
        finalize_professional_claim(case_context, research, draft)
        _deterministic_pre_qa(case_context, research, draft)
        _apply_verified_article_353(case_context, research, draft, filing_date=_today_kz())
        # Article 353 may alter monetary relief; finalize/recalculate once more.
        finalize_professional_claim(case_context, research, draft)
        _deterministic_pre_qa(case_context, research, draft)

        deterministic = deterministic_claim_preflight(case_context, research, draft)
        quality = assess_document_quality("claim", case_context, research, draft)
        LOGGER.info(
            "FINALIZED_PROFESSIONAL_CLAIM score=%.1f ready=%s deterministic=%s blockers=%s",
            quality.score,
            quality.ready,
            deterministic[:6],
            quality.hard_blockers[:6],
        )

        if quality.ready and not deterministic:
            draft.status = VerificationStatus.VERIFIED
            draft.verification_notes.clear()
            return draft

        draft.status = VerificationStatus.NEEDS_VERIFICATION
        remaining = list(dict.fromkeys([*deterministic, *quality.hard_blockers]))
        final_score = min(quality.score, 6.9 if deterministic else quality.score)
        draft.verification_notes = [
            f"SENIOR_PREFLIGHT_SCORE: {final_score:.1f}/10 — "
            + ("; ".join(remaining[:6]) or "не достигнут порог 8.5")
        ]
        return draft
