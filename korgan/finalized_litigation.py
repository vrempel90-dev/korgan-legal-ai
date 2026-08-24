from __future__ import annotations

import logging

from korgan import document_quality as _dq
from korgan import senior_claim_preflight as _sp
from korgan.claim_filing_completeness import enforce_article148_party_completeness
from korgan.claim_quality_hotfix import FILING_ACTION_PREFIX, ProductionClaimService
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
    """Preserve legacy cleanup, then let the professional router own final duty."""
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
    """Current production quality core plus deterministic professional release gates."""

    async def draft_claim(
        self,
        case_context: str,
        research: LegalResearch,
        language: str = "ru",
    ) -> ClaimDraft:
        draft = await super().draft_claim(case_context, research, language=language)

        # Remove serialization/intake artefacts before any filing calculation or
        # quality score sees them. This changes formatting noise only, never a
        # legal conclusion, amount or factual proposition.
        sanitize_claim_filing_text(draft)

        # Contract/source materials often identify a future claimant as Supplier,
        # Customer, Contractor, Creditor, etc. If the model preserved the party
        # name but omitted BIN/IIN in the court caption, restore only the exact
        # identifier that is source-bound to that same party. Never infer party
        # type from the selected court or from the opposing party's identifier.
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

        # Article 353 may add a verified monetary component. Re-finalize price,
        # then re-run the deterministic duty router from the actual final prayer.
        finalize_professional_claim(case_context, research, draft, language=language)
        sanitize_claim_filing_text(draft)
        _safe_deterministic_pre_qa(case_context, research, draft)

        # Article 148 is a final filing-readiness gate, not an intake form and
        # not a reusable legal-grounding invariant. It is deliberately applied
        # only here, immediately before senior preflight/export readiness.
        enforce_article148_party_completeness(draft)

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
