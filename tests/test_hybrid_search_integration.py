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

DB_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="TEST_DATABASE_URL is required")


class HybridTestEmbeddingProvider(EmbeddingProvider):
    @property
    def model(self) -> str:
        return "test-hybrid-3072"

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for content in texts:
            vector = [0.0] * EMBEDDING_DIMENSIONS
            # Both free-text queries deliberately point semantically at article 353.
            # For the explicit 683 query this proves the deterministic locator boost
            # can override a conflicting semantic signal.
            if content in {
                "статья 683 ГК РК",
                "ответственность за неисполнение обязательства",
            } or "Статья 353" in content:
                vector[0] = 1.0
            elif "Статья 683" in content:
                vector[1] = 1.0
            else:
                vector[2] = 1.0
            vectors.append(vector)
        return vectors


def _build_search() -> HybridSearchService:
    assert DB_URL is not None
    subprocess.run(["alembic", "upgrade", "head"], check=True, env={**os.environ, "DATABASE_URL": DB_URL})
    engine = create_engine(DB_URL)
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE legal_research_candidates, legal_norms CASCADE"))
    repo = LegalNormRepository(engine)
    seed_path = Path(__file__).parents[1] / "data" / "canonical" / "kz_reference_norms.yaml"
    load_canonical_seed(seed_path, repo)
    provider = HybridTestEmbeddingProvider()
    indexer = CorpusEmbeddingIndexer(repo, provider)
    assert indexer.index_missing_canonical(batch_size=100).indexed > 0
    return HybridSearchService(repo, provider)


def test_exact_article_locator_683_is_ranked_first() -> None:
    search = _build_search()
    hits = search.search("статья 683 ГК РК", event_date=date(2026, 8, 15), limit=3)
    assert hits
    assert hits[0].norm.article_number == "683"
    assert hits[0].exact_article_boost == pytest.approx(1.0)
    assert hits[0].total_score > hits[1].total_score


def test_free_text_query_uses_semantic_component() -> None:
    search = _build_search()
    hits = search.search(
        "ответственность за неисполнение обязательства",
        event_date=date(2026, 8, 15),
        limit=3,
    )
    assert hits
    assert hits[0].norm.article_number == "353"
    assert hits[0].semantic_score > 0.99
    assert hits[0].exact_article_boost == 0.0
