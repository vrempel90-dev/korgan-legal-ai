from decimal import Decimal

from korgan_legal_ai.audit.hash_chain import HashChainAuditLog
from korgan_legal_ai.domain.models import (
    DocumentType,
    Evidence,
    Fact,
    Financials,
    LegalArea,
    LockedCase,
    Party,
    PartyRole,
    RoutingDecision,
    VerificationStatus,
)
from korgan_legal_ai.drafting.debt_claim import DebtClaimDrafter
from korgan_legal_ai.orchestration.debt_claim import DebtClaimWorkflow
from korgan_legal_ai.procedural.checker import ProceduralChecker
from korgan_legal_ai.research.gateway import CitationGateway


def _case() -> LockedCase:
    fact = Fact(statement="Ответчик не возвратил 1 000 000 тенге")
    return LockedCase(
        raw_text="Взыскать долг",
        parties=[
            Party(name="ТОО Кредитор", role=PartyRole.CREDITOR),
            Party(name="ТОО Должник", role=PartyRole.DEBTOR),
        ],
        facts=[fact],
        evidence=[Evidence(title="Договор займа", supports_fact_ids=[fact.id])],
        financials=Financials(principal=Decimal("1000000")),
    )


def _routing() -> RoutingDecision:
    return RoutingDecision(
        document_type=DocumentType.CLAIM,
        legal_area=LegalArea.DEBT_RECOVERY,
        confidence=1,
        rationale="test",
    )


def test_debt_claim_runs_end_to_end_without_api_key():
    workflow = DebtClaimWorkflow(
        procedural=ProceduralChecker(CitationGateway()),
        drafter=DebtClaimDrafter(),
    )
    result = workflow.run(_case(), _routing())
    assert result.qa.passed is True
    assert "ТОО Кредитор" in result.document.text
    assert "ТОО Должник" in result.document.text
    assert "1000000" in result.document.text
    assert result.document.needs_verification
    assert all(
        source.status == VerificationStatus.NEEDS_VERIFICATION
        for item in result.procedural.items
        for source in item.sources
    )
    assert workflow.audit.verify() is True


def test_house_style_review_runs_after_procedural_and_draft_before_final_qa():
    audits: list[HashChainAuditLog] = []

    def audit_factory() -> HashChainAuditLog:
        audit = HashChainAuditLog()
        audits.append(audit)
        return audit

    workflow = DebtClaimWorkflow(
        procedural=ProceduralChecker(CitationGateway()),
        drafter=DebtClaimDrafter(),
        audit_factory=audit_factory,
    )
    result = workflow.run(_case(), _routing())

    assert result.qa.passed is True
    events = [entry.event for entry in audits[0].entries]
    assert events.index("procedural_checked") < events.index("house_style_review")
    assert events.index("house_style_review") < events.index("final_qa")

    style_payload = next(
        entry.payload for entry in audits[0].entries if entry.event == "house_style_review"
    )
    assert style_payload["rule_set_version"] == 1
    assert style_payload["findings"]
    assert all(set(item) == {"rule_id", "satisfied"} for item in style_payload["findings"])
    # Presentation audit must never duplicate the client/case text into its own payload.
    assert "ТОО Кредитор" not in str(style_payload)
    assert "ТОО Должник" not in str(style_payload)
    assert "Ответчик не возвратил" not in str(style_payload)
