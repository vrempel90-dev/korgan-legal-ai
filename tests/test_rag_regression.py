from __future__ import annotations

import os
import subprocess
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from korgan_legal_ai.corpus.embeddings import (
    EMBEDDING_DIMENSIONS,
    CorpusEmbeddingIndexer,
    EmbeddingProvider,
)
from korgan_legal_ai.corpus.models import CorpusStatus, LegalNorm
from korgan_legal_ai.corpus.repository import LegalNormRepository
from korgan_legal_ai.corpus.search import HybridSearchService
from korgan_legal_ai.corpus.seed import load_canonical_seed
from korgan_legal_ai.domain.models import VerificationStatus
from korgan_legal_ai.research.candidates import CandidateStatus, ResearchCandidateRepository
from korgan_legal_ai.research.fallback import (
    DiscoveredOfficialNorm,
    FallbackCitationGateway,
    OfficialFallbackSearchResult,
    OfficialFallbackService,
    OfficialSearchProvider,
)
from korgan_legal_ai.research.gateway import CanonicalHybridResearchBackend, CitationGateway
from korgan_legal_ai.research.review import LawyerReviewService

DB_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="TEST_DATABASE_URL is required")
CURRENT_DATE = date(2026, 8, 15)


class RegressionEmbeddingProvider(EmbeddingProvider):
    @property
    def model(self) -> str:
        return "test-rag-regression-3072"

    def embed(self, texts: list[str]) -> list[list[float]]:
        # Exact-article verification is intentionally independent of semantic
        # discrimination in this suite. Every vector is identical so the article
        # locator/date/status gates must do the safety-critical work.
        vector = [0.0] * EMBEDDING_DIMENSIONS
        vector[0] = 1.0
        return [list(vector) for _ in texts]


class RegressionOfficialProvider(OfficialSearchProvider):
    def __init__(self) -> None:
        self.calls: list[str] = []

    def search(self, issue: str, *, event_date: date | None) -> OfficialFallbackSearchResult:
        self.calls.append(issue)
        if "277" in issue:
            return OfficialFallbackSearchResult(
                found=True,
                candidate=DiscoveredOfficialNorm(
                    code_id="GK_RK_GENERAL",
                    law_name="Гражданский кодекс Республики Казахстан (Общая часть)",
                    article_number="277",
                    title="Срок исполнения обязательства",
                    text="Регрессионный официальный кандидат статьи 277.",
                    source_url="https://adilet.zan.kz/rus/docs/K940001000_",
                    effective_from=date(2020, 1, 1),
                ),
            )
        # A nonexistent article is never converted into a guessed fallback answer.
        return OfficialFallbackSearchResult(
            found=False,
            note="Exact requested article was not established on an allowed official source.",
        )


def test_full_rag_regression_block() -> None:
    """Acceptance suite for tasks 1-7, required green before task 9."""
    assert DB_URL is not None
    subprocess.run(
        ["alembic", "upgrade", "head"],
        check=True,
        env={**os.environ, "DATABASE_URL": DB_URL},
    )
    engine = create_engine(DB_URL)
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE legal_research_candidates, legal_norms CASCADE"))

    norm_repo = LegalNormRepository(engine)
    candidate_repo = ResearchCandidateRepository(engine)
    seed_path = Path(__file__).parents[1] / "data" / "canonical" / "kz_reference_norms.yaml"
    seeded = load_canonical_seed(seed_path, norm_repo)
    assert len(seeded) == 11

    embedder = RegressionEmbeddingProvider()
    indexed = CorpusEmbeddingIndexer(norm_repo, embedder).index_missing_canonical(batch_size=100)
    assert indexed.indexed == len(seeded)

    hybrid = HybridSearchService(norm_repo, embedder)
    primary = CitationGateway(CanonicalHybridResearchBackend(hybrid))
    official = RegressionOfficialProvider()
    fallback = FallbackCitationGateway(
        primary,
        OfficialFallbackService(official, candidate_repo),
    )
    review = LawyerReviewService(candidate_repo, norm_repo, embedder)

    # 1. Every manually reviewed reference norm is VERIFIED in the correct edition.
    for norm in seeded:
        citation = primary.research(
            f"статья {norm.article_number} {norm.law_name}",
            event_date=CURRENT_DATE.isoformat(),
        )[0]
        assert citation.status == VerificationStatus.VERIFIED
        assert citation.source_url == norm.source_url
        assert citation.effective_from == norm.effective_from
        assert citation.effective_to == norm.effective_to
        assert citation.text_excerpt == norm.text

    # 2. A nonexistent article remains NEEDS_VERIFICATION; fallback may search,
    #    but it cannot guess a norm or expose an unverified exact citation.
    nonexistent = fallback.research(
        "статья 9999 ГК РК",
        event_date=CURRENT_DATE.isoformat(),
    )
    assert nonexistent.citations[0].status == VerificationStatus.NEEDS_VERIFICATION
    assert nonexistent.citations[0].article is None
    assert nonexistent.citations[0].source_url is None
    assert nonexistent.review_card is None
    assert candidate_repo.get_pending_by_article("9999") == []

    # 3. A real-but-missing corpus article goes through fallback into pending_review,
    #    while the user still receives NEEDS_VERIFICATION.
    first_277 = fallback.research(
        "статья 277 ГК РК",
        event_date=CURRENT_DATE.isoformat(),
    )
    assert first_277.citations[0].status == VerificationStatus.NEEDS_VERIFICATION
    assert first_277.citations[0].article is None
    assert first_277.citations[0].source_url is None
    assert first_277.review_card is not None
    candidate_id = first_277.review_card.candidate_id
    pending = candidate_repo.get_by_id(candidate_id)
    assert pending is not None
    assert pending.status == CandidateStatus.PENDING_REVIEW
    calls_after_first_277 = len(official.calls)

    # 4. Explicit lawyer approval promotes it to canonical. A repeated query is
    #    VERIFIED from corpus and therefore does not invoke fallback again.
    approved = review.approve(candidate_id, reviewed_by="regression-lawyer")
    assert approved.status == CandidateStatus.APPROVED
    second_277 = fallback.research(
        "статья 277 ГК РК",
        event_date=CURRENT_DATE.isoformat(),
    )
    assert second_277.citations[0].status == VerificationStatus.VERIFIED
    assert second_277.citations[0].article == "277"
    assert second_277.review_card is None
    assert len(official.calls) == calls_after_first_277

    # 5. Two canonical editions of the same norm: historical event date must
    #    return the historical text, never the current edition.
    old = LegalNorm(
        code_id="TEST_VERSIONED",
        law_name="Тестовый версионируемый закон",
        article_number="5000",
        title="Тест редакций",
        text="Старая редакция нормы.",
        effective_from=date(2020, 1, 1),
        effective_to=date(2022, 12, 31),
        source_url="https://adilet.zan.kz/rus/docs/TEST_VERSIONED",
        status=CorpusStatus.CANONICAL,
        reviewed_by="regression-lawyer",
    )
    current = LegalNorm(
        code_id="TEST_VERSIONED",
        law_name="Тестовый версионируемый закон",
        article_number="5000",
        title="Тест редакций",
        text="Текущая редакция нормы.",
        effective_from=date(2023, 1, 1),
        source_url="https://adilet.zan.kz/rus/docs/TEST_VERSIONED",
        status=CorpusStatus.CANONICAL,
        reviewed_by="regression-lawyer",
    )
    norm_repo.upsert(old)
    norm_repo.upsert(current)
    assert CorpusEmbeddingIndexer(norm_repo, embedder).index_missing_canonical(batch_size=100).indexed == 2

    historical = primary.research(
        "статья 5000 Тестовый версионируемый закон",
        event_date="2021-06-01",
    )[0]
    present = primary.research(
        "статья 5000 Тестовый версионируемый закон",
        event_date="2024-06-01",
    )[0]
    assert historical.status == VerificationStatus.VERIFIED
    assert historical.text_excerpt == "Старая редакция нормы."
    assert historical.effective_from == date(2020, 1, 1)
    assert historical.effective_to == date(2022, 12, 31)
    assert present.status == VerificationStatus.VERIFIED
    assert present.text_excerpt == "Текущая редакция нормы."
    assert present.effective_from == date(2023, 1, 1)
