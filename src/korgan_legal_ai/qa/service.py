from __future__ import annotations

from korgan_legal_ai.domain.models import (
    CalculationResult,
    DraftDocument,
    LockedCase,
    ProceduralReport,
    QAResult,
    ResearchCitation,
)
from korgan_legal_ai.qa.policies import (
    AmountConsistencyPolicy,
    ClaimRoleDirectionPolicy,
    DateConsistencyPolicy,
    ExactCitationPolicy,
    FilingReadinessLanguagePolicy,
    OutcomeGuaranteePolicy,
    PartyPresencePolicy,
)


class FinalLegalQA:
    def __init__(self) -> None:
        self.policies = [
            PartyPresencePolicy("PARTY_PRESENCE"),
            ClaimRoleDirectionPolicy("ROLE_DIRECTION"),
            AmountConsistencyPolicy("AMOUNT_MISMATCH"),
            DateConsistencyPolicy("DATE_MISMATCH"),
            ExactCitationPolicy("UNVERIFIED_EXACT_CITATION"),
            OutcomeGuaranteePolicy("OUTCOME_GUARANTEE"),
            FilingReadinessLanguagePolicy("FILING_READINESS_LANGUAGE"),
        ]

    def check(
        self,
        case: LockedCase,
        document: DraftDocument,
        citations: list[ResearchCitation],
        *,
        procedural: ProceduralReport | None = None,
        calculation: CalculationResult | None = None,
    ) -> QAResult:
        violations = []
        for policy in self.policies:
            violations.extend(
                policy.check(
                    case=case,
                    document=document,
                    citations=citations,
                    procedural=procedural,
                    calculation=calculation,
                )
            )
        return QAResult(passed=not any(violation.blocking for violation in violations), violations=violations)
