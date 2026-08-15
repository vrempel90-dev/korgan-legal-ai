from __future__ import annotations

from korgan_legal_ai.blueprints.registry import CLAIM_DEBT_RECOVERY, resolve_blueprint
from korgan_legal_ai.domain.exceptions import ClarificationRequired
from korgan_legal_ai.domain.models import LockedCase, RoutingDecision, WorkflowResult
from korgan_legal_ai.fact_lock.grounding import validate_locked_case_grounding
from korgan_legal_ai.fact_lock.service import FactLockService
from korgan_legal_ai.orchestration.document import DocumentWorkflow
from korgan_legal_ai.router.service import TaskRouter


class LegalEngine:
    """Single public orchestration entry point for raw user/evidence text."""

    def __init__(
        self,
        *,
        fact_lock: FactLockService,
        router: TaskRouter,
        debt_claim: DocumentWorkflow,
        workflows: dict[str, DocumentWorkflow] | None = None,
    ) -> None:
        self.fact_lock = fact_lock
        self.router = router
        # Workflows are keyed by blueprint, so routing to a document type the deployment has not
        # enabled fails loudly instead of falling back to a document the user did not ask for.
        self.workflows: dict[str, DocumentWorkflow] = dict(workflows or {})
        self.workflows.setdefault(CLAIM_DEBT_RECOVERY.key, debt_claim)

    @property
    def debt_claim(self) -> DocumentWorkflow:
        return self.workflows[CLAIM_DEBT_RECOVERY.key]

    def process_prepared(self, case: LockedCase, routing: RoutingDecision) -> WorkflowResult:
        """Run the pipeline on a case that was already collected deterministically.

        The guided dialogue produces the locked case itself from validated answers, so Fact Lock
        and the router have nothing to add: the facts were typed by the user and the document type
        was chosen, not inferred. Everything after this point — verification, calculation, drafting
        and Final Legal QA — is the same pipeline the free-text path runs.
        """
        blueprint = resolve_blueprint(routing.document_type, routing.legal_area)
        workflow = self.workflows.get(blueprint.key) if blueprint is not None else None
        if workflow is None:
            raise NotImplementedError(
                f"Workflow is not implemented yet: {routing.document_type}/{routing.legal_area}"
            )
        return workflow.run(case, routing)

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

        blueprint = resolve_blueprint(routing.document_type, routing.legal_area)
        workflow = self.workflows.get(blueprint.key) if blueprint is not None else None
        if workflow is None:
            raise NotImplementedError(
                f"Workflow is not implemented yet: {routing.document_type}/{routing.legal_area}"
            )
        return workflow.run(downstream_case, routing)
