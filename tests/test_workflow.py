from decimal import Decimal

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


def test_debt_claim_runs_end_to_end_without_api_key():
    fact = Fact(statement="Ответчик не возвратил 1 000 000 тенге")
    case = LockedCase(
        raw_text="Взыскать долг",
        parties=[
            Party(name="ТОО Кредитор", role=PartyRole.CREDITOR),
            Party(name="ТОО Должник", role=PartyRole.DEBTOR),
        ],
        facts=[fact],
        evidence=[Evidence(title="Договор займа", supports_fact_ids=[fact.id])],
        financials=Financials(principal=Decimal("1000000")),
    )
    routing = RoutingDecision(
        document_type=DocumentType.CLAIM,
        legal_area=LegalArea.DEBT_RECOVERY,
        confidence=1,
        rationale="test",
    )
    workflow = DebtClaimWorkflow(
        procedural=ProceduralChecker(CitationGateway()),
        drafter=DebtClaimDrafter(),
    )
    result = workflow.run(case, routing)
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
