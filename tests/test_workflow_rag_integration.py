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
from korgan_legal_ai.procedural_rules.basis import LegalBasisVerifier
from korgan_legal_ai.procedural_rules.jurisdiction import JurisdictionResolver
from korgan_legal_ai.procedural_rules.repository import ProceduralRuleRepository
from korgan_legal_ai.procedural_rules.seed import load_procedural_rule_seed
from korgan_legal_ai.procedural_rules.state_duty import StateDutyCalculator
from korgan_legal_ai.research.gateway import CanonicalHybridResearchBackend, CitationGateway

DB_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="TEST_DATABASE_URL is required")
AS_OF_DATE = date(2026, 8, 15)


class NoopEmbeddingProvider(EmbeddingProvider):
    @property
    def model(self) -> str:
        return "workflow-noop-3072"

    def embed(self, texts: list[str]) -> list[list[float]]:
        vector = [0.0] * EMBEDDING_DIMENSIONS
        vector[0] = 1.0
        return [list(vector) for _ in texts]


def _build_workflow():
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
    norm_repository = LegalNormRepository(engine)
    load_canonical_seed(base / "data" / "canonical" / "kz_reference_norms.yaml", norm_repository)
    load_canonical_seed(
        base / "data" / "canonical" / "kz_procedural_basis_norms.yaml",
        norm_repository,
    )
    rule_repository = ProceduralRuleRepository(engine)
    load_procedural_rule_seed(
        base / "data" / "rules" / "kz_procedural_rules.yaml",
        rule_repository,
    )

    gateway = CitationGateway(
        CanonicalHybridResearchBackend(
            HybridSearchService(norm_repository, NoopEmbeddingProvider())
        )
    )
    verifier = LegalBasisVerifier(gateway)
    checker = ProceduralChecker(
        gateway,
        state_duty_calculator=StateDutyCalculator(rule_repository, verifier),
        jurisdiction_resolver=JurisdictionResolver(rule_repository, verifier),
    )
    workflow = DebtClaimWorkflow(
        procedural=checker,
        drafter=DebtClaimDrafter(),
        as_of_date_provider=lambda: AS_OF_DATE,
    )
    return engine, workflow


def _case() -> tuple[LockedCase, RoutingDecision]:
    fact = Fact(statement="ТОО Должник не оплатил задолженность в размере 1 000 000 тенге.")
    case = LockedCase(
        raw_text="Взыскать задолженность между двумя ТОО.",
        parties=[
            Party(name="ТОО Кредитор", role=PartyRole.CREDITOR),
            Party(
                name="ТОО Должник",
                role=PartyRole.DEBTOR,
                address="г. Алматы, тестовый адрес",
            ),
        ],
        facts=[fact],
        evidence=[Evidence(title="Договор", supports_fact_ids=[fact.id])],
        financials=Financials(principal=Decimal("1000000")),
    )
    routing = RoutingDecision(
        document_type=DocumentType.CLAIM,
        legal_area=LegalArea.DEBT_RECOVERY,
        confidence=1.0,
        rationale="test",
    )
    return case, routing


def test_debt_workflow_uses_verified_duty_and_jurisdiction_but_keeps_other_gaps_closed():
    _engine, workflow = _build_workflow()
    case, routing = _case()
    result = workflow.run(case, routing)

    items = {item.name: item for item in result.procedural.items}
    assert items["state_duty"].status == VerificationStatus.VERIFIED
    assert "30000.00 KZT" in items["state_duty"].conclusion
    assert {citation.article for citation in items["state_duty"].sources} == {
        "665, часть 1, пункт 1",
        "7",
    }

    assert items["jurisdiction"].status == VerificationStatus.VERIFIED
    assert "специализированный межрайонный экономический суд" in items["jurisdiction"].conclusion
    assert {citation.article for citation in items["jurisdiction"].sources} == {
        "27, часть 1",
        "29, часть 2",
    }

    assert items["limitation"].status == VerificationStatus.NEEDS_VERIFICATION
    assert "state_duty" not in result.document.needs_verification
    assert "jurisdiction" not in result.document.needs_verification
    assert "limitation" in result.document.needs_verification
    assert "статья 665, часть 1, пункт 1" in result.document.text
    assert result.qa.passed is True
    assert workflow.audit.verify() is True


def test_missing_state_duty_basis_never_releases_a_guessed_amount():
    engine, workflow = _build_workflow()
    with engine.begin() as connection:
        connection.execute(text("""
            DELETE FROM legal_norms
            WHERE code_id='TAX_RK_2025'
              AND article_number='665'
              AND part='1'
              AND point='1'
        """))

    case, routing = _case()
    result = workflow.run(case, routing)
    item = next(item for item in result.procedural.items if item.name == "state_duty")
    assert item.status == VerificationStatus.NEEDS_VERIFICATION
    assert "30000.00 KZT" not in item.conclusion
    assert "state_duty" in result.document.needs_verification
