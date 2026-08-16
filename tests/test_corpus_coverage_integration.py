"""Adding a norm must actually remove a blocker, and a stale norm must say so."""
from __future__ import annotations

import os
import subprocess
from datetime import date

import pytest
from sqlalchemy import create_engine, text

from korgan_legal_ai.corpus.embeddings import EMBEDDING_DIMENSIONS, EmbeddingProvider
from korgan_legal_ai.corpus.repository import LegalNormRepository
from korgan_legal_ai.corpus.search import HybridSearchService
from korgan_legal_ai.corpus.seed import load_canonical_seed
from korgan_legal_ai.domain.models import VerificationStatus
from korgan_legal_ai.evals.cases import EVAL_CASES
from korgan_legal_ai.evals.coverage import LAW_DRIVEN_ITEMS, build_coverage_report
from korgan_legal_ai.procedural.checker import ProceduralChecker
from korgan_legal_ai.procedural_rules.basis import LegalBasisVerifier
from korgan_legal_ai.procedural_rules.jurisdiction import JurisdictionResolver
from korgan_legal_ai.procedural_rules.repository import ProceduralRuleRepository
from korgan_legal_ai.procedural_rules.seed import load_procedural_rule_seed
from korgan_legal_ai.procedural_rules.state_duty import StateDutyCalculator
from korgan_legal_ai.research.gateway import CanonicalHybridResearchBackend, CitationGateway

DB_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="TEST_DATABASE_URL is required")
AS_OF = date(2026, 8, 15)
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class ZeroEmbeddings(EmbeddingProvider):
    """Exact locators need no embedding; free-text search finds nothing rather than guessing."""

    @property
    def model(self) -> str:
        return "coverage-integration-zero"

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * EMBEDDING_DIMENSIONS for _ in texts]


def _engine():
    assert DB_URL is not None
    subprocess.run(
        ["alembic", "upgrade", "head"],
        check=True,
        env={**os.environ, "DATABASE_URL": DB_URL},
    )
    return create_engine(DB_URL)


def _reset(engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                TRUNCATE procedural_deadline_bases, procedural_deadline_rules,
                         procedural_jurisdiction_rules, procedural_mrp_values,
                         procedural_state_duty_rules, legal_research_candidates,
                         legal_norms CASCADE
                """
            )
        )


def _checker(engine) -> ProceduralChecker:
    norms = LegalNormRepository(engine)
    gateway = CitationGateway(
        CanonicalHybridResearchBackend(HybridSearchService(norms, ZeroEmbeddings()))
    )
    rules = ProceduralRuleRepository(engine)
    verifier = LegalBasisVerifier(gateway)
    return ProceduralChecker(
        gateway,
        state_duty_calculator=StateDutyCalculator(rules, verifier),
        jurisdiction_resolver=JurisdictionResolver(rules, verifier),
    )


@pytest.fixture()
def seeded():
    engine = _engine()
    _reset(engine)
    norms = LegalNormRepository(engine)
    base = os.path.join(REPO_ROOT, "data")
    load_canonical_seed(os.path.join(base, "canonical", "kz_reference_norms.yaml"), norms)
    load_canonical_seed(os.path.join(base, "canonical", "kz_procedural_basis_norms.yaml"), norms)
    load_procedural_rule_seed(
        os.path.join(base, "rules", "kz_procedural_rules.yaml"), ProceduralRuleRepository(engine)
    )
    return engine


def test_empty_corpus_is_the_baseline_and_blocks_every_law_driven_item() -> None:
    report = build_coverage_report(EVAL_CASES, corpus_checker=None, as_of=AS_OF)

    assert report.baseline_blockers > 0
    assert report.resolved == 0
    assert report.reduction_percent == 0.0
    # With no corpus, nothing about the law can be settled.
    assert report.remaining_blockers == report.baseline_blockers
    assert not report.norms


def test_a_populated_corpus_measurably_removes_blockers(seeded) -> None:
    report = build_coverage_report(EVAL_CASES, corpus_checker=_checker(seeded), as_of=AS_OF)

    assert report.remaining_blockers < report.baseline_blockers
    assert report.reduction_percent > 0
    # Progress is attributed to specific norms, not just counted.
    assert report.norms
    top = report.norms[0]
    assert top.unblocked_count > 0
    assert top.source_url.startswith("https://")


def test_state_duty_stops_being_a_blocker_once_its_basis_is_in_the_corpus(seeded) -> None:
    before = build_coverage_report(EVAL_CASES, corpus_checker=None, as_of=AS_OF)
    after = build_coverage_report(EVAL_CASES, corpus_checker=_checker(seeded), as_of=AS_OF)

    def duty_blockers(report) -> int:
        return sum(
            1
            for item in report.current
            if item.item == "state_duty" and item.status == VerificationStatus.NEEDS_VERIFICATION
        )

    assert duty_blockers(before) > 0
    assert duty_blockers(after) < duty_blockers(before)


def test_remaining_blockers_separate_missing_norms_from_missing_facts(seeded) -> None:
    report = build_coverage_report(EVAL_CASES, corpus_checker=_checker(seeded), as_of=AS_OF)

    # Some items stay unresolved because the matter lacks a fact, not because law is missing.
    # Counting those as corpus work would make further norm entry look useless.
    assert report.remaining_norm_blockers <= report.remaining_blockers
    for outcome in report.current:
        assert outcome.item in LAW_DRIVEN_ITEMS


def test_an_overdue_norm_is_used_but_flagged_rather_than_passed_off_as_current(seeded) -> None:
    norms = LegalNormRepository(seeded)
    with seeded.begin() as connection:
        connection.execute(
            text(
                "UPDATE legal_norms SET next_review_date = :stale WHERE code_id = 'GPK_RK'"
            ),
            {"stale": date(2026, 1, 1)},
        )

    citations = CitationGateway(
        CanonicalHybridResearchBackend(HybridSearchService(norms, ZeroEmbeddings()))
    ).research_locator(
        code_id="GPK_RK", article_number="148", part="4", event_date=AS_OF.isoformat()
    )

    citation = citations[0]
    # Still usable: an overdue review does not make the recorded wording wrong.
    assert citation.status == VerificationStatus.VERIFIED
    # But the reader is told, rather than being left to assume it was checked recently.
    assert citation.review_overdue is True
    assert "переверификация" in (citation.verification_note or "")


def test_a_norm_within_its_review_window_carries_no_warning(seeded) -> None:
    norms = LegalNormRepository(seeded)
    with seeded.begin() as connection:
        connection.execute(
            text("UPDATE legal_norms SET next_review_date = :fresh WHERE code_id = 'GPK_RK'"),
            {"fresh": date(2027, 1, 1)},
        )

    citations = CitationGateway(
        CanonicalHybridResearchBackend(HybridSearchService(norms, ZeroEmbeddings()))
    ).research_locator(
        code_id="GPK_RK", article_number="148", part="4", event_date=AS_OF.isoformat()
    )

    assert citations[0].review_overdue is False
    assert "переверификация" not in (citations[0].verification_note or "")


def test_a_norm_added_through_the_curator_is_found_by_the_gateway(seeded) -> None:
    """The whole point of the tool: what a lawyer enters becomes citable law for the engine."""
    from korgan_legal_ai.corpus.curation import CorpusCurator, NormSubmission

    norms = LegalNormRepository(seeded)
    curator = CorpusCurator(norms)
    body = (
        "Проверочная запись инструмента наполнения корпуса. Настоящий текст не является нормой "
        "права и подлежит замене дословным текстом статьи из официального источника."
    )
    curator.add(
        NormSubmission(
            code_id="GPK_RK",
            article_number="9001",
            part="1",
            text=body,
            effective_from=date(2026, 1, 1),
            source_url="https://adilet.zan.kz/rus/docs/K1500000377",
            reviewed_by="Тестовый юрист",
            law_name="Гражданский процессуальный кодекс Республики Казахстан",
            applicable_document_types=("claim", "appeal"),
        )
    )

    gateway = CitationGateway(
        CanonicalHybridResearchBackend(HybridSearchService(norms, ZeroEmbeddings()))
    )
    citations = gateway.research_locator(
        code_id="GPK_RK", article_number="9001", part="1", event_date=AS_OF.isoformat()
    )

    assert citations[0].status == VerificationStatus.VERIFIED
    assert citations[0].text_excerpt == body
    assert citations[0].article == "9001, часть 1"

    stored = norms.get_canonical_for_date(
        code_id="GPK_RK", article_number="9001", part="1", event_date=AS_OF
    )
    # The link to document types survives storage, so coverage reporting can use it.
    assert stored is not None
    assert sorted(stored.applicable_document_types) == ["appeal", "claim"]


def test_a_norm_not_yet_effective_is_not_citable_for_an_earlier_matter(seeded) -> None:
    from korgan_legal_ai.corpus.curation import CorpusCurator, NormSubmission

    norms = LegalNormRepository(seeded)
    CorpusCurator(norms).add(
        NormSubmission(
            code_id="GPK_RK",
            article_number="9002",
            text=(
                "Проверочная запись с будущей датой вступления в силу. Текст не является нормой "
                "права и подлежит замене юристом."
            ),
            effective_from=date(2027, 1, 1),
            source_url="https://adilet.zan.kz/rus/docs/K1500000377",
            reviewed_by="Тестовый юрист",
            applicable_document_types=("claim",),
        )
    )

    citations = CitationGateway(
        CanonicalHybridResearchBackend(HybridSearchService(norms, ZeroEmbeddings()))
    ).research_locator(
        code_id="GPK_RK", article_number="9002", event_date=AS_OF.isoformat()
    )

    # Effective-date filtering is what keeps a future redaction out of today's document.
    assert citations[0].status == VerificationStatus.NEEDS_VERIFICATION
