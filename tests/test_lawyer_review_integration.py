from __future__ import annotations

import os
import subprocess
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from korgan_legal_ai.corpus.embeddings import EMBEDDING_DIMENSIONS, CorpusEmbeddingIndexer, EmbeddingProvider
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
EVENT_DATE = date(2026, 8, 15)


class ReviewEmbeddingProvider(EmbeddingProvider):
    @property
    def model(self) -> str:
        return "test-review-3072"

    def embed(self, texts: list[str]) -> list[list[float]]:
        vector = [0.0] * EMBEDDING_DIMENSIONS
        vector[0] = 1.0
        return [list(vector) for _ in texts]


class ConfigurableOfficialProvider(OfficialSearchProvider):
    def __init__(self, article: str, *, effective_from: date | None = date(2020, 1, 1)) -> None:
        self.article = article
        self.effective_from = effective_from
        self.calls = 0

    def search(self, issue: str, *, event_date: date | None) -> OfficialFallbackSearchResult:
        self.calls += 1
        return OfficialFallbackSearchResult(
            found=True,
            candidate=DiscoveredOfficialNorm(
                code_id="GK_RK_GENERAL",
                law_name="Гражданский кодекс Республики Казахстан (Общая часть)",
                article_number=self.article,
                title=f"Тестовая статья {self.article}",
                text=f"Текст официального кандидата статьи {self.article}.",
                source_url="https://adilet.zan.kz/rus/docs/K940001000_",
                effective_from=self.effective_from,
            ),
        )


def _build(article: str = "277", *, effective_from: date | None = date(2020, 1, 1)):
    assert DB_URL is not None
    subprocess.run(["alembic", "upgrade", "head"], check=True, env={**os.environ, "DATABASE_URL": DB_URL})
    engine = create_engine(DB_URL)
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE legal_research_candidates, legal_norms CASCADE"))
    norm_repo = LegalNormRepository(engine)
    candidate_repo = ResearchCandidateRepository(engine)
    seed_path = Path(__file__).parents[1] / "data" / "canonical" / "kz_reference_norms.yaml"
    seeded = load_canonical_seed(seed_path, norm_repo)
    embedder = ReviewEmbeddingProvider()
    assert CorpusEmbeddingIndexer(norm_repo, embedder).index_missing_canonical(batch_size=100).indexed == len(seeded)
    primary = CitationGateway(CanonicalHybridResearchBackend(HybridSearchService(norm_repo, embedder)))
    provider = ConfigurableOfficialProvider(article, effective_from=effective_from)
    gateway = FallbackCitationGateway(primary, OfficialFallbackService(provider, candidate_repo))
    review = LawyerReviewService(candidate_repo, norm_repo, embedder)
    return gateway, review, provider, candidate_repo, norm_repo


def test_approve_makes_repeat_query_verified_without_second_fallback() -> None:
    gateway, review, provider, candidates, _norms = _build("277")
    first = gateway.research("статья 277 ГК РК", event_date=EVENT_DATE.isoformat())
    assert first.citations[0].status == VerificationStatus.NEEDS_VERIFICATION
    assert first.review_card is not None
    assert provider.calls == 1

    approval = review.approve(first.review_card.candidate_id, reviewed_by="lawyer-1")
    assert approval.status == CandidateStatus.APPROVED
    reviewed = candidates.get_by_id(first.review_card.candidate_id)
    assert reviewed is not None
    assert reviewed.status == CandidateStatus.APPROVED
    assert reviewed.canonical_norm_id == approval.canonical_norm_id

    second = gateway.research("статья 277 ГК РК", event_date=EVENT_DATE.isoformat())
    assert second.citations[0].status == VerificationStatus.VERIFIED
    assert second.citations[0].article == "277"
    assert provider.calls == 1
    assert second.review_card is None


def test_rejected_candidate_is_not_canonical_and_is_not_silently_reopened() -> None:
    gateway, review, provider, candidates, norms = _build("278")
    first = gateway.research("статья 278 ГК РК", event_date=EVENT_DATE.isoformat())
    assert first.review_card is not None
    candidate_id = first.review_card.candidate_id

    rejection = review.reject(candidate_id, reviewed_by="lawyer-2", reason="Текст не подтвержден")
    assert rejection.status == CandidateStatus.REJECTED
    stored = candidates.get_by_id(candidate_id)
    assert stored is not None and stored.status == CandidateStatus.REJECTED
    assert norms.get_by_locator(code_id="GK_RK_GENERAL", article_number="278") == []

    second = gateway.research("статья 278 ГК РК", event_date=EVENT_DATE.isoformat())
    assert second.citations[0].status == VerificationStatus.NEEDS_VERIFICATION
    assert second.review_card is None
    assert provider.calls == 2
    stored_again = candidates.get_by_id(candidate_id)
    assert stored_again is not None and stored_again.status == CandidateStatus.REJECTED


def test_approval_without_established_effective_date_fails_closed() -> None:
    gateway, review, _provider, candidates, norms = _build("279", effective_from=None)
    first = gateway.research("статья 279 ГК РК", event_date=EVENT_DATE.isoformat())
    assert first.review_card is not None
    with pytest.raises(ValueError, match="effective_from"):
        review.approve(first.review_card.candidate_id, reviewed_by="lawyer-3")
    stored = candidates.get_by_id(first.review_card.candidate_id)
    assert stored is not None and stored.status == CandidateStatus.PENDING_REVIEW
    assert norms.get_by_locator(code_id="GK_RK_GENERAL", article_number="279") == []
