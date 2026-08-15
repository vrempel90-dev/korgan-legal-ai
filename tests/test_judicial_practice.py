"""Judicial practice strengthens an argument and can never substitute for a verified norm."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from korgan_legal_ai.blueprints.registry import CLAIM_DEBT_RECOVERY
from korgan_legal_ai.corpus.practice import (
    JudicialAct,
    JudicialPracticeService,
    PracticeStatus,
)
from korgan_legal_ai.domain.models import (
    DocumentType,
    Evidence,
    Fact,
    Financials,
    LegalArea,
    LockedCase,
    Party,
    PartyRole,
    ProcedureFacts,
    RoutingDecision,
)
from korgan_legal_ai.drafting.debt_claim import DebtClaimDrafter
from korgan_legal_ai.orchestration.debt_claim import DebtClaimWorkflow
from korgan_legal_ai.procedural.checker import ProceduralChecker
from korgan_legal_ai.research.gateway import CitationGateway


class FakeEmbeddings:
    def embed(self, values: list[str]) -> list[list[float]]:
        return [[0.1, 0.2, 0.3] for _ in values]


class FakeRepository:
    """Stands in for the database, returning already-scored rows."""

    def __init__(self, rows) -> None:
        self.rows = rows
        self.queries: list[tuple[str, str | None]] = []

    def hybrid_search(self, *, query_text, embedding, legal_area, limit):
        self.queries.append((query_text, legal_area))
        return self.rows[:limit]


def _act(**overrides) -> JudicialAct:
    payload = {
        "case_number": "2-1234/2025",
        "court_name": "СМЭС города Алматы",
        "decided_on": date(2025, 11, 12),
        "instance": "первая инстанция",
        "legal_area": "debt_recovery",
        "summary": "Взыскана задолженность по договору перевозки",
        "text_excerpt": "Суд удовлетворил требования о взыскании основного долга.",
        "source_url": "https://gov.kz/act/2-1234-2025",
        "status": PracticeStatus.CANONICAL,
    }
    payload.update(overrides)
    return JudicialAct(**payload)


def _case() -> LockedCase:
    fact = Fact(statement="Перевозка выполнена, оплата не поступила")
    return LockedCase(
        raw_text="",
        parties=[
            Party(name="ТОО Альфа", role=PartyRole.CREDITOR),
            Party(name="ТОО Бета", role=PartyRole.DEBTOR),
        ],
        facts=[fact],
        evidence=[Evidence(title="Договор", supports_fact_ids=[fact.id])],
        financials=Financials(contract_amount=Decimal("1000000")),
        procedure=ProcedureFacts(obligation_due_date=date(2026, 6, 1)),
    )


def _run(practice) -> object:
    workflow = DebtClaimWorkflow(
        procedural=ProceduralChecker(CitationGateway()),
        drafter=DebtClaimDrafter(),
        practice=practice,
        as_of_date_provider=lambda: date(2026, 8, 15),
    )
    return workflow.run(
        _case(),
        RoutingDecision(
            document_type=DocumentType.CLAIM,
            legal_area=LegalArea.DEBT_RECOVERY,
            confidence=1,
            rationale="test",
        ),
    )


def test_empty_corpus_produces_no_practice_section() -> None:
    service = JudicialPracticeService(FakeRepository([]), FakeEmbeddings())

    result = _run(service)

    assert "СУДЕБНАЯ ПРАКТИКА" not in result.document.text
    # An unpopulated corpus is not a verification gap: nothing about the document is unresolved.
    assert "practice" not in result.document.needs_verification


def test_no_practice_service_configured_is_not_an_error() -> None:
    result = _run(None)

    assert result.qa.passed
    assert "СУДЕБНАЯ ПРАКТИКА" not in result.document.text


def test_relevant_reviewed_practice_is_cited_with_its_source() -> None:
    repository = FakeRepository([(_act(), 0.81, 0.6, 0.79)])
    service = JudicialPracticeService(repository, FakeEmbeddings())

    result = _run(service)

    text = result.document.text
    assert "СУДЕБНАЯ ПРАКТИКА" in text
    assert "2-1234/2025" in text
    assert "https://gov.kz/act/2-1234-2025" in text
    # The query is built from locked facts, and the search is scoped to the matter's legal area.
    assert repository.queries == [("Перевозка выполнена, оплата не поступила", "debt_recovery")]


def test_weak_matches_are_dropped_rather_than_offered() -> None:
    repository = FakeRepository([(_act(), 0.40, 0.10, 0.31)])
    service = JudicialPracticeService(repository, FakeEmbeddings())

    result = _run(service)

    assert "СУДЕБНАЯ ПРАКТИКА" not in result.document.text


def test_practice_from_an_unapproved_domain_is_refused() -> None:
    repository = FakeRepository(
        [(_act(source_url="https://random-blog.example/case"), 0.90, 0.8, 0.86)]
    )
    service = JudicialPracticeService(repository, FakeEmbeddings())

    result = _run(service)

    assert "random-blog" not in result.document.text
    assert "СУДЕБНАЯ ПРАКТИКА" not in result.document.text


def test_practice_never_makes_an_unverified_norm_citable() -> None:
    """A decision mentioning an article does not authorise the draft to cite that article."""
    repository = FakeRepository(
        [
            (
                _act(
                    summary="Суд применил статью 272 ГК РК",
                    cited_articles=["272"],
                ),
                0.85,
                0.7,
                0.80,
            )
        ]
    )
    service = JudicialPracticeService(repository, FakeEmbeddings())

    result = _run(service)

    # Final Legal QA still governs: the article appears only inside the quoted summary of the act,
    # and the legal-grounds section still reports that the applicable norms need verification.
    assert result.qa.passed
    assert "NEEDS_VERIFICATION" in result.document.text
    grounds = result.document.text.split("ПРАВОВОЕ ОБОСНОВАНИЕ", maxsplit=1)[1]
    assert "конкретные нормы материального и процессуального права" in grounds


def test_retrieval_failure_degrades_to_no_practice_instead_of_failing() -> None:
    class ExplodingRepository:
        def hybrid_search(self, **kwargs):
            raise RuntimeError("practice corpus unavailable")

    service = JudicialPracticeService(ExplodingRepository(), FakeEmbeddings())

    result = _run(service)

    assert result.qa.passed
    assert "СУДЕБНАЯ ПРАКТИКА" not in result.document.text


def test_only_the_claim_blueprints_carry_a_practice_section() -> None:
    assert any(
        section.heading == "СУДЕБНАЯ ПРАКТИКА" for section in CLAIM_DEBT_RECOVERY.sections
    )
