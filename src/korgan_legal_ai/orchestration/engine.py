from __future__ import annotations

from korgan_legal_ai.domain.exceptions import ClarificationRequired
from korgan_legal_ai.domain.models import DocumentType, LegalArea, WorkflowResult
from korgan_legal_ai.fact_lock.grounding import validate_locked_case_grounding
from korgan_legal_ai.fact_lock.service import FactLockService
from korgan_legal_ai.orchestration.debt_claim import DebtClaimWorkflow
from korgan_legal_ai.router.service import TaskRouter


class LegalEngine:
    """Single public orchestration entry point for raw user/evidence text."""

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

        grounding_issues = validate_locked_case_grounding(raw_text, case)
        if grounding_issues:
            raise ClarificationRequired(grounding_issues)

        routing = self.router.route(case)

        # Raw text has served its only trusted purpose once Fact Lock and grounding/routing are
        # complete. The workflow receives structured locked facts only. This keeps instructions
        # embedded in uploaded evidence out of drafting/QA model prompts and also prevents raw
        # document text from being copied into the in-memory hash-chain audit payload.
        downstream_case = case.model_copy(update={"raw_text": ""})

        if routing.document_type == DocumentType.CLAIM and routing.legal_area == LegalArea.DEBT_RECOVERY:
            return self.debt_claim.run(downstream_case, routing)
        raise NotImplementedError(
            f"Workflow is not implemented yet: {routing.document_type}/{routing.legal_area}"
        )
