from __future__ import annotations

from datetime import date
from typing import Callable

from korgan_legal_ai.audit.hash_chain import HashChainAuditLog
from korgan_legal_ai.calculations.service import CalculationLayer
from korgan_legal_ai.domain.exceptions import LegalQABlocked
from korgan_legal_ai.domain.models import LegalArea, LockedCase, RoutingDecision, WorkflowResult
from korgan_legal_ai.drafting.debt_claim import DebtClaimDrafter
from korgan_legal_ai.evidence.service import EvidenceMapBuilder
from korgan_legal_ai.house_style import load_rules, review_claim_presentation
from korgan_legal_ai.procedural.checker import ProceduralChecker
from korgan_legal_ai.qa.service import FinalLegalQA


class _AuditVerificationSnapshot:
    """Compatibility view that never retains audit payloads from a completed legal request."""

    def __init__(self, verified: bool) -> None:
        self._verified = verified

    def verify(self) -> bool:
        return self._verified


class DebtClaimWorkflow:
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
        self.procedural = procedural
        self.drafter = drafter
        self.evidence = evidence or EvidenceMapBuilder()
        self.calculations = calculations or CalculationLayer()
        self.qa = qa or FinalLegalQA()
        self.audit_factory = audit_factory or HashChainAuditLog
        self.as_of_date_provider = as_of_date_provider or date.today
        self._last_audit_verified = False

    @property
    def audit(self) -> _AuditVerificationSnapshot:
        """Expose verification compatibility without keeping any prior case/audit entries."""
        return _AuditVerificationSnapshot(self._last_audit_verified)

    @staticmethod
    def _audit_house_style(audit: HashChainAuditLog, document, calculation, *, event: str) -> None:
        """Run presentation-only checks without changing legal content or verification state.

        The audit stores only rule ids and booleans. It never stores the document text or a style
        finding detail, so client facts cannot leak through this new layer.
        """
        rule_set = load_rules()
        findings = review_claim_presentation(document, calculation, rule_set=rule_set)
        audit.append(
            event,
            {
                "rule_set_version": rule_set.version,
                "findings": [
                    {"rule_id": finding.rule_id, "satisfied": finding.satisfied}
                    for finding in findings
                ],
            },
        )

    def run(self, case: LockedCase, routing: RoutingDecision) -> WorkflowResult:
        if routing.legal_area != LegalArea.DEBT_RECOVERY:
            raise ValueError("DebtClaimWorkflow only accepts debt_recovery routing")

        self._last_audit_verified = False
        # A fresh chain per legal request prevents audit state from crossing user/case boundaries
        # when the workflow instance is reused by a long-running Telegram process.
        audit = self.audit_factory()

        audit.append("case_locked", case.model_dump(mode="json"))
        audit.append("task_routed", routing.model_dump(mode="json"))

        evidence_map = self.evidence.build(case)
        as_of_date = self.as_of_date_provider()
        calculation = self.calculations.calculate_money(
            case.financials,
            obligation_due_date=case.procedure.obligation_due_date,
            as_of_date=as_of_date,
        )
        audit.append("calculation_completed", calculation.model_dump(mode="json"))
        audit.append("procedural_reference_date", {"date": as_of_date.isoformat()})
        procedural = self.procedural.check(
            case,
            routing=routing,
            calculation=calculation,
            as_of_date=as_of_date,
        )
        audit.append("procedural_checked", procedural.model_dump(mode="json"))

        document = self.drafter.draft(case, procedural, evidence_map, calculation)
        self._audit_house_style(audit, document, calculation, event="house_style_review")

        citations = [citation for item in procedural.items for citation in item.sources]
        qa_result = self.qa.check(
            case,
            document,
            citations,
            calculation=calculation,
            procedural=procedural,
        )
        audit.append("final_qa", qa_result.model_dump(mode="json"))

        # The legal safety rule is "do not release an unsafe draft", not "withhold every useful
        # document when the LLM made a formatting or citation mistake". If an LLM draft is blocked,
        # build a deterministic lawyer-review draft from the already locked facts and verified
        # procedural output. The fallback contains explicit NEEDS_VERIFICATION markers and must pass
        # the exact same Final Legal QA before anything is released.
        if not qa_result.passed and self.drafter.provider is not None and self.drafter.model:
            audit.append(
                "llm_draft_blocked_by_final_qa",
                {"violation_codes": [violation.code for violation in qa_result.violations]},
            )
            fallback = self.drafter.safe_fallback(case, procedural, evidence_map, calculation)
            self._audit_house_style(
                audit,
                fallback,
                calculation,
                event="safe_fallback_house_style_review",
            )
            fallback_qa = self.qa.check(
                case,
                fallback,
                citations,
                calculation=calculation,
                procedural=procedural,
            )
            audit.append("safe_fallback_final_qa", fallback_qa.model_dump(mode="json"))
            if fallback_qa.passed:
                document = fallback
                qa_result = fallback_qa
                audit.append(
                    "safe_fallback_selected",
                    {
                        "readiness": document.readiness,
                        "needs_verification": document.needs_verification,
                    },
                )

        if not qa_result.passed:
            self._last_audit_verified = audit.verify()
            raise LegalQABlocked("Final Legal QA blocked document output")

        audit.append(
            "document_released_for_human_review",
            {"readiness": document.readiness, "needs_verification": document.needs_verification},
        )
        self._last_audit_verified = audit.verify()
        return WorkflowResult(
            locked_case=case,
            routing=routing,
            procedural=procedural,
            evidence_map=evidence_map,
            calculation=calculation,
            document=document,
            qa=qa_result,
            audit_head=audit.head,
        )
