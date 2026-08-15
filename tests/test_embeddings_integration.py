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
from korgan_legal_ai.corpus.seed import load_canonical_seed

DB_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="TEST_DATABASE_URL is required")


class DeterministicEmbeddingProvider(EmbeddingProvider):
    @property
    def model(self) -> str:
        return "test-deterministic-3072"

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for content in texts:
            vector = [0.0] * EMBEDDING_DIMENSIONS
            if "Статья 353" in content:
                vector[0] = 1.0
            elif "Статья 683" in content:
                vector[1] = 1.0
            else:
                vector[2] = 1.0
            vectors.append(vector)
        return vectors


def test_one_norm_equals_one_chunk_and_semantic_search_finds_353_top3() -> None:
    assert DB_URL is not None
    subprocess.run(["alembic", "upgrade", "head"], check=True, env={**os.environ, "DATABASE_URL": DB_URL})
    engine = create_engine(DB_URL)
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE legal_research_candidates, legal_norms CASCADE"))
    repo = LegalNormRepository(engine)
    seed_path = Path(__file__).parents[1] / "data" / "canonical" / "kz_reference_norms.yaml"
    seeded = load_canonical_seed(seed_path, repo)

    indexer = CorpusEmbeddingIndexer(repo, DeterministicEmbeddingProvider())
    result = indexer.index_missing_canonical(batch_size=100)
    assert result.indexed == len(seeded)

    with engine.connect() as connection:
        embedded_count = connection.execute(
            text("SELECT count(*) FROM legal_norms WHERE status='canonical' AND embedding IS NOT NULL")
        ).scalar_one()
    assert embedded_count == len(seeded)

    query = [0.0] * EMBEDDING_DIMENSIONS
    query[0] = 1.0
    matches = repo.semantic_search(embedding=query, event_date=date(2026, 8, 15), limit=3)
    assert len(matches) == 3
    assert any(norm.article_number == "353" for norm, _ in matches)
    assert matches[0][0].article_number == "353"
