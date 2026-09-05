from __future__ import annotations

import logging

from korgan import document_quality as _dq
from korgan import senior_claim_preflight as _sp
from korgan.claim_filing_completeness import enforce_article148_party_completeness
from korgan.claim_quality_hotfix import FILING_ACTION_PREFIX, ProductionClaimService
from korgan.claim_release_consistency import enforce_release_consistency
from korgan.claim_substantive_basis import enforce_substantive_basis
from korgan.claim_state_duty import apply_professional_state_duty
from korgan.fast_v2_production_legal import _deterministic_pre_qa
from korgan.late_interest_hotfix import _apply_verified_article_353, _today_kz
from korgan.legal_types import ClaimDraft, LegalResearch, VerificationStatus
from korgan.professional_claim_finalizer import finalize_professional_claim

LOGGER = logging.getLogger(__name__)


def _safe_deterministic_pre_qa(case_context: str, research: LegalResearch, draft: ClaimDraft) -> None:
    """Preserve legacy cleanup, then let the professional router own final duty."""
    _deterministic_pre_qa(case_context, research, draft)
    apply_professional_state_duty(case_context, research, draft)


class FinalizedProductionClaimService(ProductionClaimService):
    """Current production quality core plus deterministic professional release gates."""

    async def draft_claim(
        self,
        case_context: str,
        research: LegalResearch,
        language: str = "ru",
    ) -> ClaimDraft:
        draft = await super().draft_claim(case_context, research, language=language)

        finalize_professional_claim(case_context, research, draft, language=language)
        _safe_deterministic_pre_qa(case_context, research, draft)
        _apply_verified_article_353(case_context, research, draft, filing_date=_today_kz())

        # Article 353 may add a verified monetary component. Re-finalize price,
        # then re-run the deterministic duty router from the actual final prayer.
        finalize_professional_claim(case_context, research, draft, language=language)
        _safe_deterministic_pre_qa(case_context, research, draft)

        # Article 148 is a final filing-readiness gate, not an intake form and
        # not a reusable legal-grounding invariant. It is deliberately applied
        # only here, immediately before senior preflight/export readiness.
        enforce_article148_party_completeness(draft)

        # Слои выше устанавливают суд и пошлину независимо друг от друга и
        # каждый оставляет собственную задачу «уточнить». Когда факт уже
        # установлен, задача о нём — противоречие, а не подстраховка: документ
        # одновременно называл суд и просил его подтвердить.
        enforce_release_consistency(draft, case_context, research)

        # Правовое обоснование пересобирается целиком из подтверждённых выводов
        # исследования. Всё, что не прошло сверку, отбрасывается — и вместе с
        # ним могла уйти норма о существе долга, оставив иск на одних
        # процессуальных статьях. Отбрасывание правильно, молчание — нет.
        substantive = enforce_substantive_basis(research, draft)

        deterministic = _sp.deterministic_claim_preflight(case_context, research, draft)
        if substantive:
            deterministic = list(dict.fromkeys([*substantive, *deterministic]))
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
            enforce_release_consistency(draft, case_context, research)
            return draft

        draft.status = VerificationStatus.NEEDS_VERIFICATION
        remaining = list(dict.fromkeys([*deterministic, *quality.hard_blockers]))
        final_score = min(quality.score, 6.9 if deterministic else quality.score)
        score_note = (
            f"SENIOR_PREFLIGHT_SCORE: {final_score:.1f}/10 — "
            + ("; ".join(remaining[:6]) or "не достигнут порог 8.5")
        )
        draft.verification_notes = list(dict.fromkeys([*filing, *nonfiling, score_note]))
        # Пересборка перечня возвращает в него замечания гейтов качества: среди
        # них снова оказываются задачи об уже установленных суде и пошлине.
        enforce_release_consistency(draft, case_context, research)
        return draft
