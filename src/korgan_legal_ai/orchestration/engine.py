from __future__ import annotations

from korgan_legal_ai.domain.models import DocumentType, LegalArea, WorkflowResult
from korgan_legal_ai.fact_lock.service import FactLockService
from korgan_legal_ai.orchestration.debt_claim import DebtClaimWorkflow
from korgan_legal_ai.router.service import TaskRouter


class LegalEngine:
    """Single public orchestration entry point for raw user text."""

    def __init__(
        self,
        *,
        fact_lock: FactLockService,
        router: TaskRouter,
        debt_claim: DebtClaimWorkflow,
    ) -> None:
        self.fact_lock = fact_lock
        self.router = router
        self.debt_claim = debt_claim

    def process(self, raw_text: str) -> WorkflowResult:
        case = self.fact_lock.lock(raw_text)
        routing = self.router.route(case)
        if routing.document_type == DocumentType.CLAIM and routing.legal_area == LegalArea.DEBT_RECOVERY:
            return self.debt_claim.run(case, routing)
        raise NotImplementedError(
            f"Workflow is not implemented yet: {routing.document_type}/{routing.legal_area}"
        )
