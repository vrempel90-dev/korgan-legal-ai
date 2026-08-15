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
from korgan_legal_ai.corpus.repository import LegalNormRepository
from korgan_legal_ai.corpus.search import HybridSearchService
from korgan_legal_ai.corpus.seed import load_canonical_seed
from korgan_legal_ai.domain.models import VerificationStatus
from korgan_legal_ai.research.gateway import CanonicalHybridResearchBackend, CitationGateway

DB_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="TEST_DATABASE_URL is required")
EVENT_DATE = date(2026, 8, 15)


class GatewayTestEmbeddingProvider(EmbeddingProvider):
    @property
    def model(self) -> str:
        return "test-citation-gateway-3072"

    def embed(self, texts: list[str]) -> list[list[float]]:
        # Deliberately make semantic similarity non-discriminating. Exact article
        # verification must therefore depend on canonical locator matching rather
        # than a semantic guess.
        vector = [0.0] * EMBEDDING_DIMENSIONS
        vector[0] = 1.0
        return [list(vector) for _ in texts]


def _build_gateway():
    assert DB_URL is not None
    subprocess.run(["alembic", "upgrade", "head"], check=True, env={**os.environ, "DATABASE_URL": DB_URL})
    engine = create_engine(DB_URL)
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE legal_research_candidates, legal_norms CASCADE"))
    repo = LegalNormRepository(engine)
    seed_path = Path(__file__).parents[1] / "data" / "canonical" / "kz_reference_norms.yaml"
    seeded = load_canonical_seed(seed_path, repo)
    provider = GatewayTestEmbeddingProvider()
    indexed = CorpusEmbeddingIndexer(repo, provider).index_missing_canonical(batch_size=100)
    assert indexed.indexed == len(seeded)
    search = HybridSearchService(repo, provider)
    gateway = CitationGateway(CanonicalHybridResearchBackend(search))
    return gateway, seeded


def test_all_reference_norms_are_verified_with_correct_edition() -> None:
    gateway, seeded = _build_gateway()
    assert len(seeded) == 11
    for norm in seeded:
        result = gateway.research(
            f"статья {norm.article_number} {norm.law_name}",
            event_date=EVENT_DATE.isoformat(),
        )[0]
        assert result.status == VerificationStatus.VERIFIED
        assert result.source_url == norm.source_url
        assert result.effective_from == norm.effective_from
        assert result.effective_to == norm.effective_to
        assert result.text_excerpt == norm.text
        assert result.article is not None
        assert result.article.startswith(norm.article_number)
        if norm.part:
            assert f"часть {norm.part}" in result.article
        if norm.point:
            assert f"пункт {norm.point}" in result.article


def test_nonexistent_article_9999_fails_closed_without_guessing() -> None:
    gateway, _seeded = _build_gateway()
    result = gateway.research("статья 9999 ГК РК", event_date=EVENT_DATE.isoformat())[0]
    assert result.status == VerificationStatus.NEEDS_VERIFICATION
    assert result.article is None
    assert result.source_url is None
    assert result.text_excerpt is None


def test_missing_or_invalid_event_date_never_verifies() -> None:
    gateway, _seeded = _build_gateway()
    missing = gateway.research("статья 353 ГК РК")[0]
    invalid = gateway.research("статья 353 ГК РК", event_date="15.08.2026")[0]
    assert missing.status == VerificationStatus.NEEDS_VERIFICATION
    assert invalid.status == VerificationStatus.NEEDS_VERIFICATION
