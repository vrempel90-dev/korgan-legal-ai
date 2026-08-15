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
from korgan_legal_ai.research.candidates import ResearchCandidateRepository
from korgan_legal_ai.research.fallback import (
    DiscoveredOfficialNorm,
    FallbackCitationGateway,
    OfficialFallbackSearchResult,
    OfficialFallbackService,
    OfficialSearchProvider,
)
from korgan_legal_ai.research.gateway import CanonicalHybridResearchBackend, CitationGateway

DB_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="TEST_DATABASE_URL is required")
EVENT_DATE = date(2026, 8, 15)


class SameEmbeddingProvider(EmbeddingProvider):
    @property
    def model(self) -> str:
        return "test-fallback-3072"

    def embed(self, texts: list[str]) -> list[list[float]]:
        vector = [0.0] * EMBEDDING_DIMENSIONS
        vector[0] = 1.0
        return [list(vector) for _ in texts]


class FakeOfficialProvider(OfficialSearchProvider):
    def __init__(self, source_url: str = "https://adilet.zan.kz/rus/docs/K940001000_") -> None:
        self.source_url = source_url
        self.calls = 0

    def search(self, issue: str, *, event_date: date | None) -> OfficialFallbackSearchResult:
        self.calls += 1
        return OfficialFallbackSearchResult(
            found=True,
            candidate=DiscoveredOfficialNorm(
                code_id="GK_RK_GENERAL",
                law_name="Гражданский кодекс Республики Казахстан (Общая часть)",
                article_number="277",
                title="Срок исполнения обязательства",
                text="Тестовый кандидат статьи 277 только для pending_review.",
                source_url=self.source_url,
                effective_from=None,
            ),
        )


def _build(provider: OfficialSearchProvider):
    assert DB_URL is not None
    subprocess.run(["alembic", "upgrade", "head"], check=True, env={**os.environ, "DATABASE_URL": DB_URL})
    engine = create_engine(DB_URL)
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE legal_research_candidates, legal_norms"))
    norm_repo = LegalNormRepository(engine)
    candidate_repo = ResearchCandidateRepository(engine)
    seed_path = Path(__file__).parents[1] / "data" / "canonical" / "kz_reference_norms.yaml"
    seeded = load_canonical_seed(seed_path, norm_repo)
    embedder = SameEmbeddingProvider()
    assert CorpusEmbeddingIndexer(norm_repo, embedder).index_missing_canonical(batch_size=100).indexed == len(seeded)
    primary = CitationGateway(CanonicalHybridResearchBackend(HybridSearchService(norm_repo, embedder)))
    fallback = OfficialFallbackService(provider, candidate_repo)
    return FallbackCitationGateway(primary, fallback), candidate_repo


def test_existing_official_missing_corpus_is_staged_but_user_stays_needs_verification() -> None:
    provider = FakeOfficialProvider()
    gateway, repo = _build(provider)
    outcome = gateway.research("статья 277 ГК РК", event_date=EVENT_DATE.isoformat())
    assert provider.calls == 1
    assert outcome.citations[0].status == VerificationStatus.NEEDS_VERIFICATION
    assert outcome.citations[0].article is None
    assert outcome.review_card is not None
    assert outcome.review_card.article_number == "277"
    assert outcome.review_card.proposed_status == "pending_review"
    staged = repo.get_pending_by_article("277")
    assert len(staged) == 1
    assert staged[0].status == "pending_review"


def test_disallowed_domain_is_never_staged_or_used() -> None:
    provider = FakeOfficialProvider("https://example.com/fake-law")
    gateway, repo = _build(provider)
    outcome = gateway.research("статья 277 ГК РК", event_date=EVENT_DATE.isoformat())
    assert outcome.citations[0].status == VerificationStatus.NEEDS_VERIFICATION
    assert outcome.review_card is None
    assert repo.count_pending() == 0


def test_canonical_verified_result_does_not_call_fallback() -> None:
    provider = FakeOfficialProvider()
    gateway, repo = _build(provider)
    outcome = gateway.research("статья 353 ГК РК", event_date=EVENT_DATE.isoformat())
    assert outcome.citations[0].status == VerificationStatus.VERIFIED
    assert provider.calls == 0
    assert outcome.review_card is None
    assert repo.count_pending() == 0
