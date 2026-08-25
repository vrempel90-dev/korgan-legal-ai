from __future__ import annotations

import logging

from korgan.claim_filing_completeness import enforce_article148_party_completeness
from korgan.claim_profile_grounding import ground_claim_profile_from_corpus
from korgan.claim_quality_hotfix import (
    FILING_ACTION_PREFIX,
    ProductionClaimService,
    _patched_assess_document_quality,
    _patched_preflight,
)
from korgan.claim_state_duty import StateDutyDecision, apply_professional_state_duty
from korgan.fast_v2_production_legal import _deterministic_pre_qa
from korgan.filing_text_sanitizer import sanitize_claim_filing_text
from korgan.late_interest_hotfix import _apply_verified_article_353, _today_kz
from korgan.legal_types import ClaimDraft, LegalResearch, VerificationStatus
from korgan.party_identity import hydrate_claimant_identity
from korgan.professional_claim_finalizer import finalize_professional_claim

LOGGER = logging.getLogger(__name__)


def _safe_deterministic_pre_qa(
    case_context: str,
    research: LegalResearch,
    draft: ClaimDraft,
) -> StateDutyDecision:
    _deterministic_pre_qa(case_context, research, draft)
    decision = apply_professional_state_duty(case_context, research, draft)
    LOGGER.info(
        "STATE_DUTY_FINAL mode=%s amount=%s deferred=%s exempt=%s needs_review=%s price=%r claimant=%r",
        decision.mode,
        decision.amount,
        decision.deferred,
        decision.exempt,
        decision.needs_review,
        draft.price_of_claim,
        draft.claimant[:4],
    )
    return decision


class FinalizedProductionClaimService(ProductionClaimService):
    """Current production quality core plus deterministic professional release gates.

    Goal-v2 invariant I8 requires the repaired and finalized stages to use the
    same filing-vs-substance scoring policy.  The old code repaired with the
    production-scoped patched assessor, then finalized with the raw global
    assessor; filing-only Article 148 notes therefore reduced 8.4 -> 7.8 after
    repair had already finished.  Finalization now uses the exact same assessor
    and preflight semantics as the repaired stage.
    """

    async def draft_claim(
        self,
        case_context: str,
        research: LegalResearch,
        language: str = "ru",
    ) -> ClaimDraft:
        ground_claim_profile_from_corpus(case_context, research)

        draft = await super().draft_claim(case_context, research, language=language)
        repaired_quality = _patched_assess_document_quality("claim", case_context, research, draft)
        repaired_score = float(repaired_quality.score)

        sanitize_claim_filing_text(draft)

        identity = hydrate_claimant_identity(case_context, draft.claimant)
        if identity is not None:
            LOGGER.info(
                "CLAIMANT_IDENTITY_RESTORED kind=%s identifier=%s%s",
                identity.kind,
                identity.identifier_label,
                identity.identifier,
            )

        finalize_professional_claim(case_context, research, draft, language=language)
        _safe_deterministic_pre_qa(case_context, research, draft)
        _apply_verified_article_353(case_context, research, draft, filing_date=_today_kz())

        finalize_professional_claim(case_context, research, draft, language=language)
        sanitize_claim_filing_text(draft)
        _safe_deterministic_pre_qa(case_context, research, draft)

        enforce_article148_party_completeness(draft)

        # IMPORTANT: same policy as FastProfessional repaired preflight. Filing
        # data the user must provide remains a filing action, not a new internal
        # quality penalty introduced after repair.
        deterministic = _patched_preflight(case_context, research, draft)
        quality = _patched_assess_document_quality("claim", case_context, research, draft)
        finalized_score = float(quality.score)
        monotonic = finalized_score >= repaired_score
        LOGGER.info(
            "PIPELINE_INVARIANT I8 repaired_score=%.1f finalized_score=%.1f result=%s",
            repaired_score,
            finalized_score,
            "PASS" if monotonic else "FAIL",
        )
        LOGGER.info(
            "FINALIZED_PROFESSIONAL_CLAIM score=%.1f ready=%s deterministic=%s blockers=%s",
            quality.score,
            quality.ready,
            deterministic[:6],
            quality.hard_blockers[:6],
        )

        # If a truly new substantive blocker appears despite using the same
        # policy, never hide it behind the numeric score. It is an internal
        # quality defect and must be visible to downstream Goal-v2 delivery.
        if not monotonic:
            marker = (
                "[СВЕРИТЬ: финальная детерминированная обработка выявила новый внутренний дефект; "
                f"оценка {repaired_score:.1f} -> {finalized_score:.1f}]"
            )
            if marker not in draft.verification_notes:
                draft.verification_notes.append(marker)

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
