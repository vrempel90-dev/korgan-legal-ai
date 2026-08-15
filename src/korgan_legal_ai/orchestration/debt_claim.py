from __future__ import annotations

from datetime import date
from typing import Callable

from korgan_legal_ai.audit.hash_chain import HashChainAuditLog
from korgan_legal_ai.calculations.service import CalculationLayer
from korgan_legal_ai.domain.exceptions import LegalQABlocked
from korgan_legal_ai.domain.models import LegalArea, LockedCase, RoutingDecision, WorkflowResult
from korgan_legal_ai.drafting.debt_claim import DebtClaimDrafter
from korgan_legal_ai.evidence.service import EvidenceMapBuilder
from korgan_legal_ai.procedural.checker import ProceduralChecker
from korgan_legal_ai.qa.service import FinalLegalQA


class DebtClaimWorkflow:
    def __init__(
        self,
        *,
        procedural: ProceduralChecker,
        drafter: DebtClaimDrafter,
        evidence: EvidenceMapBuilder | None = None,
        calculations: CalculationLayer | None = None,
        qa: FinalLegalQA | None = None,
        audit: HashChainAuditLog | None = None,
        as_of_date_provider: Callable[[], date] | None = None,
    ) -> None:
        self.procedural = procedural
        self.drafter = drafter
        self.evidence = evidence or EvidenceMapBuilder()
        self.calculations = calculations or CalculationLayer()
        self.qa = qa or FinalLegalQA()
        self.audit = audit or HashChainAuditLog()
        self.as_of_date_provider = as_of_date_provider or date.today

    def run(self, case: LockedCase, routing: RoutingDecision) -> WorkflowResult:
        if routing.legal_area != LegalArea.DEBT_RECOVERY:
            raise ValueError("DebtClaimWorkflow only accepts debt_recovery routing")

        self.audit.append("case_locked", case.model_dump(mode="json"))
        self.audit.append("task_routed", routing.model_dump(mode="json"))

        evidence_map = self.evidence.build(case)
        calculation = self.calculations.calculate_money(case.financials)
        self.audit.append("calculation_completed", calculation.model_dump(mode="json"))

        as_of_date = self.as_of_date_provider()
        self.audit.append("procedural_reference_date", {"date": as_of_date.isoformat()})
        procedural = self.procedural.check(
            case,
            routing=routing,
            calculation=calculation,
            as_of_date=as_of_date,
        )
        self.audit.append("procedural_checked", procedural.model_dump(mode="json"))

        document = self.drafter.draft(case, procedural, evidence_map, calculation)
        citations = [citation for item in procedural.items for citation in item.sources]
        qa_result = self.qa.check(case, document, citations)
        self.audit.append("final_qa", qa_result.model_dump(mode="json"))

        if not qa_result.passed:
            raise LegalQABlocked("Final Legal QA blocked document output")

        self.audit.append(
            "document_released_for_human_review",
            {"readiness": document.readiness, "needs_verification": document.needs_verification},
        )
        return WorkflowResult(
            locked_case=case,
            routing=routing,
            procedural=procedural,
            evidence_map=evidence_map,
            calculation=calculation,
            document=document,
            qa=qa_result,
            audit_head=self.audit.head,
        )
