from __future__ import annotations

from datetime import date
from typing import Callable

from korgan_legal_ai.audit.hash_chain import HashChainAuditLog
from korgan_legal_ai.blueprints.registry import CLAIM_DEBT_RECOVERY
from korgan_legal_ai.calculations.service import CalculationLayer
from korgan_legal_ai.domain.models import LegalArea, LockedCase, RoutingDecision, WorkflowResult
from korgan_legal_ai.drafting.debt_claim import DebtClaimDrafter
from korgan_legal_ai.evidence.service import EvidenceMapBuilder
from korgan_legal_ai.orchestration.document import DocumentWorkflow
from korgan_legal_ai.procedural.checker import ProceduralChecker
from korgan_legal_ai.qa.service import FinalLegalQA


class DebtClaimWorkflow(DocumentWorkflow):
    """Debt-recovery claim pipeline.

    Kept as a named workflow because it carries the project's longest regression history. It is now
    the debt-recovery blueprint applied to the shared document pipeline, with the extra guard that
    it refuses any routing that is not a debt-recovery claim.
    """

    def __init__(
        self,
        *,
        procedural: ProceduralChecker,
        drafter: DebtClaimDrafter,
        evidence: EvidenceMapBuilder | None = None,
        calculations: CalculationLayer | None = None,
        qa: FinalLegalQA | None = None,
        audit_factory: Callable[[], HashChainAuditLog] | None = None,
        as_of_date_provider: Callable[[], date] | None = None,
    ) -> None:
        super().__init__(
            blueprint=CLAIM_DEBT_RECOVERY,
            procedural=procedural,
            drafter=drafter,
            evidence=evidence,
            calculations=calculations,
            qa=qa,
            audit_factory=audit_factory,
            as_of_date_provider=as_of_date_provider,
        )

    def run(self, case: LockedCase, routing: RoutingDecision) -> WorkflowResult:
        if routing.legal_area != LegalArea.DEBT_RECOVERY:
            raise ValueError("DebtClaimWorkflow only accepts debt_recovery routing")
        return super().run(case, routing)
