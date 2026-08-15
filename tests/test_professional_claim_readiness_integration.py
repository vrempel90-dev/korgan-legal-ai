from __future__ import annotations

import os
import subprocess
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from korgan_legal_ai.corpus.embeddings import EMBEDDING_DIMENSIONS, EmbeddingProvider
from korgan_legal_ai.corpus.repository import LegalNormRepository
from korgan_legal_ai.corpus.search import HybridSearchService
from korgan_legal_ai.corpus.seed import load_canonical_seed
from korgan_legal_ai.domain.models import (
    DocumentType,
    Evidence,
    EvidenceKind,
    Fact,
    FilingMode,
    Financials,
    LegalArea,
    LockedCase,
    Party,
    PartyRole,
    ProcedureFacts,
    ReadinessStatus,
    RepresentativeKind,
    RoutingDecision,
    VerificationStatus,
)
from korgan_legal_ai.drafting.debt_claim import DebtClaimDrafter
from korgan_legal_ai.orchestration.debt_claim import DebtClaimWorkflow
from korgan_legal_ai.procedural.checker import ProceduralChecker
from korgan_legal_ai.procedural_rules.basis import LegalBasisVerifier
from korgan_legal_ai.procedural_rules.deadlines import DeadlineCalculator, WorkingDayCalendar
from korgan_legal_ai.procedural_rules.jurisdiction import JurisdictionResolver
from korgan_legal_ai.procedural_rules.repository import ProceduralRuleRepository
from korgan_legal_ai.procedural_rules.seed import load_procedural_rule_seed
from korgan_legal_ai.procedural_rules.state_duty import StateDutyCalculator
from korgan_legal_ai.research.gateway import CanonicalHybridResearchBackend, CitationGateway

DB_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="TEST_DATABASE_URL is required")
AS_OF = date(2026, 8, 15)


class NoopEmbeddingProvider(EmbeddingProvider):
    @property
    def model(self) -> str:
        return "professional-claim-noop-3072"

    def embed(self, texts: list[str]) -> list[list[float]]:
        vector = [0.0] * EMBEDDING_DIMENSIONS
        vector[0] = 1.0
        return [list(vector) for _ in texts]


class VerifiedWeekdayCalendar(WorkingDayCalendar):
    """Test stand-in for a separately reviewed Kazakhstan work/non-work calendar."""

    def is_working_day(self, value: date) -> bool | None:
        return value.weekday() < 5


def _checker() -> ProceduralChecker:
    assert DB_URL is not None
    subprocess.run(
        ["alembic", "upgrade", "head"],
        check=True,
        env={**os.environ, "DATABASE_URL": DB_URL},
    )
    engine = create_engine(DB_URL)
    with engine.begin() as connection:
        connection.execute(text("""
            TRUNCATE procedural_deadline_bases, procedural_deadline_rules,
                     procedural_jurisdiction_rules, procedural_mrp_values,
                     procedural_state_duty_rules, legal_research_candidates, legal_norms CASCADE
        """))

    base = Path(__file__).parents[1]
    norms = LegalNormRepository(engine)
    load_canonical_seed(base / "data" / "canonical" / "kz_reference_norms.yaml", norms)
    load_canonical_seed(base / "data" / "canonical" / "kz_procedural_basis_norms.yaml", norms)
    rules = ProceduralRuleRepository(engine)
    load_procedural_rule_seed(base / "data" / "rules" / "kz_procedural_rules.yaml", rules)

    gateway = CitationGateway(
        CanonicalHybridResearchBackend(HybridSearchService(norms, NoopEmbeddingProvider()))
    )
    verifier = LegalBasisVerifier(gateway)
    return ProceduralChecker(
        gateway,
        state_duty_calculator=StateDutyCalculator(rules, verifier),
        jurisdiction_resolver=JurisdictionResolver(rules, verifier),
        deadline_calculator=DeadlineCalculator(rules, verifier, VerifiedWeekdayCalendar()),
    )


def test_complete_company_debt_case_reaches_final_human_review_without_guesses() -> None:
    debt_fact = Fact(statement="Ответчик не оплатил поставленный товар на сумму 1 000 000 тенге.")
    case = LockedCase(
        raw_text="Полный проверочный кейс взыскания договорной задолженности между ТОО.",
        parties=[
            Party(
                name="ТОО Кредитор",
                role=PartyRole.CLAIMANT,
                iin_bin="123456789012",
                address="г. Алматы, ул. Тестовая, 1",
            ),
            Party(
                name="ТОО Должник",
                role=PartyRole.DEFENDANT,
                iin_bin="210987654321",
                address="г. Алматы, ул. Проверочная, 2",
            ),
        ],
        facts=[debt_fact],
        evidence=[
            Evidence(title="Договор поставки", kind=EvidenceKind.CONTRACT, supports_fact_ids=[debt_fact.id]),
            Evidence(title="Накладная", kind=EvidenceKind.PRIMARY_DOCUMENT, supports_fact_ids=[debt_fact.id]),
            Evidence(title="Претензия", kind=EvidenceKind.PRETRIAL_DEMAND),
            Evidence(title="Подтверждение доставки претензии", kind=EvidenceKind.PRETRIAL_DELIVERY),
            Evidence(title="Приказ о назначении директора", kind=EvidenceKind.AUTHORITY),
            Evidence(title="Справка о государственной регистрации ТОО", kind=EvidenceKind.REGISTRATION),
            Evidence(title="Платежный документ по государственной пошлине", kind=EvidenceKind.STATE_DUTY_PAYMENT),
        ],
        financials=Financials(principal=Decimal("1000000")),
        procedure=ProcedureFacts(
            obligation_due_date=date(2026, 1, 15),
            pretrial_required_by_contract=True,
            pretrial_demand_sent_date=date(2026, 2, 1),
            representative_kind=RepresentativeKind.DIRECTOR,
            filing_mode=FilingMode.ELECTRONIC,
        ),
    )
    routing = RoutingDecision(
        document_type=DocumentType.CLAIM,
        legal_area=LegalArea.DEBT_RECOVERY,
        confidence=1.0,
        rationale="verified integration fixture",
    )

    workflow = DebtClaimWorkflow(
        procedural=_checker(),
        drafter=DebtClaimDrafter(),
        as_of_date_provider=lambda: AS_OF,
    )
    result = workflow.run(case, routing)

    status_by_name = {item.name: item.status for item in result.procedural.items}
    assert status_by_name == {
        "jurisdiction": VerificationStatus.VERIFIED,
        "pretrial": VerificationStatus.VERIFIED,
        "limitation": VerificationStatus.VERIFIED,
        "state_duty": VerificationStatus.VERIFIED,
        "authority": VerificationStatus.VERIFIED,
        "attachments": VerificationStatus.VERIFIED,
    }
    assert result.document.needs_verification == []
    assert result.document.readiness == ReadinessStatus.READY_FOR_FINAL_HUMAN_REVIEW
    assert result.qa.passed is True
    assert "Государственная пошлина: 30000.00 KZT" in result.document.text
    assert "15.01.2026" in result.document.text
    assert "01.02.2026" in result.document.text
    assert "статья 148, часть 2, пункт 6" in result.document.text
    assert "статья 149, часть 1, пункт 7" in result.document.text
    assert workflow.audit.verify() is True
