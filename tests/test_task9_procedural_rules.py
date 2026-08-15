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
from korgan_legal_ai.domain.models import VerificationStatus
from korgan_legal_ai.procedural_rules.basis import LegalBasisVerifier
from korgan_legal_ai.procedural_rules.deadlines import DeadlineCalculator, WorkingDayCalendar
from korgan_legal_ai.procedural_rules.jurisdiction import JurisdictionResolver
from korgan_legal_ai.procedural_rules.repository import ProceduralRuleRepository
from korgan_legal_ai.procedural_rules.seed import load_procedural_rule_seed
from korgan_legal_ai.procedural_rules.state_duty import StateDutyCalculator
from korgan_legal_ai.research.gateway import CanonicalHybridResearchBackend, CitationGateway

DB_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="TEST_DATABASE_URL is required")
EVENT_DATE = date(2026, 8, 15)


class NoopEmbeddingProvider(EmbeddingProvider):
    @property
    def model(self) -> str:
        return "task9-noop-3072"

    def embed(self, texts: list[str]) -> list[list[float]]:
        vector = [0.0] * EMBEDDING_DIMENSIONS
        vector[0] = 1.0
        return [list(vector) for _ in texts]


class WeekdaysOnlyVerifiedCalendar(WorkingDayCalendar):
    """Test fixture standing in for a separately verified work calendar."""

    def is_working_day(self, value: date) -> bool | None:
        return value.weekday() < 5


def _build():
    assert DB_URL is not None
    subprocess.run(["alembic", "upgrade", "head"], check=True, env={**os.environ, "DATABASE_URL": DB_URL})
    engine = create_engine(DB_URL)
    with engine.begin() as connection:
        connection.execute(text("""
            TRUNCATE procedural_deadline_bases, procedural_deadline_rules,
                     procedural_jurisdiction_rules, procedural_mrp_values,
                     procedural_state_duty_rules, legal_research_candidates, legal_norms CASCADE
        """))
    norm_repo = LegalNormRepository(engine)
    base = Path(__file__).parents[1]
    load_canonical_seed(base / "data" / "canonical" / "kz_reference_norms.yaml", norm_repo)
    load_canonical_seed(base / "data" / "canonical" / "kz_procedural_basis_norms.yaml", norm_repo)
    rules = ProceduralRuleRepository(engine)
    assert load_procedural_rule_seed(base / "data" / "rules" / "kz_procedural_rules.yaml", rules) == 6
    gateway = CitationGateway(CanonicalHybridResearchBackend(HybridSearchService(norm_repo, NoopEmbeddingProvider())))
    verifier = LegalBasisVerifier(gateway)
    return engine, norm_repo, rules, verifier


def test_state_duty_and_jurisdiction_for_legal_entity_debt_are_verified() -> None:
    _engine, _norms, rules, verifier = _build()
    duty = StateDutyCalculator(rules, verifier).calculate(
        claim_amount_kzt=Decimal("1000000"), claimant_type="legal_entity",
        claim_type="property", event_date=EVENT_DATE,
    )
    assert duty.status == VerificationStatus.VERIFIED
    assert duty.rate_percent == Decimal("3.000000")
    assert duty.uncapped_amount_kzt == Decimal("30000.00")
    assert duty.cap_kzt == Decimal("86500000.00")
    assert duty.amount_kzt == Decimal("30000.00")
    assert {citation.article for citation in duty.citations} == {"665, часть 1, пункт 1", "7"}

    jurisdiction = JurisdictionResolver(rules, verifier).resolve(
        plaintiff_type="legal_entity", defendant_type="legal_entity",
        dispute_type="commercial_debt", event_date=EVENT_DATE,
    )
    assert jurisdiction.status == VerificationStatus.VERIFIED
    assert jurisdiction.court_type == "specialized_interdistrict_economic_court"
    assert jurisdiction.territorial_rule == "defendant_location"
    assert {citation.article for citation in jurisdiction.citations} == {"27, часть 1", "29, часть 2"}


def test_missing_legal_basis_forces_state_duty_to_needs_verification_without_amount() -> None:
    engine, _norms, rules, verifier = _build()
    with engine.begin() as connection:
        connection.execute(text("""
            DELETE FROM legal_norms
            WHERE code_id='TAX_RK_2025' AND article_number='665' AND part='1' AND point='1'
        """))
    result = StateDutyCalculator(rules, verifier).calculate(
        claim_amount_kzt=Decimal("1000000"), claimant_type="legal_entity",
        claim_type="property", event_date=EVENT_DATE,
    )
    assert result.status == VerificationStatus.NEEDS_VERIFICATION
    assert result.amount_kzt is None
    assert result.uncapped_amount_kzt is None


def test_deadline_formulas_verify_bases_and_fail_closed_without_work_calendar() -> None:
    _engine, _norms, rules, verifier = _build()
    fail_closed = DeadlineCalculator(rules, verifier)
    limitation = fail_closed.calculate(
        rule_code="general_debt_limitation",
        trigger_date=date(2026, 1, 15), event_date=EVENT_DATE,
    )
    assert limitation.status == VerificationStatus.NEEDS_VERIFICATION
    assert limitation.period_start == date(2026, 1, 16)
    assert limitation.nominal_deadline == date(2029, 1, 15)
    assert limitation.final_deadline is None

    verified_calendar = DeadlineCalculator(rules, verifier, WeekdaysOnlyVerifiedCalendar())
    appeal = verified_calendar.calculate(
        rule_code="civil_appeal_general",
        trigger_date=date(2026, 8, 3), event_date=EVENT_DATE,
    )
    assert appeal.status == VerificationStatus.VERIFIED
    assert appeal.period_start == date(2026, 8, 4)
    assert appeal.nominal_deadline == date(2026, 9, 3)
    assert appeal.final_deadline == date(2026, 9, 3)
