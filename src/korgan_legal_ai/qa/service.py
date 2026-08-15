from __future__ import annotations

from korgan_legal_ai.domain.models import DraftDocument, LockedCase, QAResult, ResearchCitation
from korgan_legal_ai.qa.policies import (
    ExactCitationPolicy,
    FilingReadinessLanguagePolicy,
    OutcomeGuaranteePolicy,
    PartyPresencePolicy,
    ClaimRoleDirectionPolicy,
)


class FinalLegalQA:
    def __init__(self) -> None:
        self.policies = [
            PartyPresencePolicy("PARTY_PRESENCE"),
            ClaimRoleDirectionPolicy("ROLE_DIRECTION"),
            ExactCitationPolicy("UNVERIFIED_EXACT_CITATION"),
            OutcomeGuaranteePolicy("OUTCOME_GUARANTEE"),
            FilingReadinessLanguagePolicy("FILING_READINESS_LANGUAGE"),
        ]

    def check(self, case: LockedCase, document: DraftDocument, citations: list[ResearchCitation]) -> QAResult:
        violations = []
        for policy in self.policies:
            violations.extend(policy.check(case=case, document=document, citations=citations))
        return QAResult(passed=not any(v.blocking for v in violations), violations=violations)
