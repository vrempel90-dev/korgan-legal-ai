from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from korgan_legal_ai.corpus.embeddings import EmbeddingProvider
from korgan_legal_ai.corpus.models import LegalNorm
from korgan_legal_ai.corpus.repository import LegalNormRepository

_ARTICLE_PATTERN = re.compile(r"\b(?:статья|ст\.?)[\s№]*([0-9]+(?:[-–][0-9]+)?)\b", re.IGNORECASE)


@dataclass(frozen=True)
class HybridSearchHit:
    norm: LegalNorm
    semantic_score: float
    lexical_score: float
    exact_article_boost: float
    total_score: float


class HybridSearchService:
    """Hybrid retrieval over canonical, date-applicable legal norms only.

    Semantic similarity supplies recall. PostgreSQL full-text rank supplies lexical
    precision. An explicit article locator is deterministic and receives a boost
    large enough to outrank merely semantically similar provisions.
    """

    def __init__(self, repository: LegalNormRepository, embedding_provider: EmbeddingProvider) -> None:
        self.repository = repository
        self.embedding_provider = embedding_provider

    @staticmethod
    def extract_article_number(query: str) -> str | None:
        match = _ARTICLE_PATTERN.search(query)
        if match is None:
            return None
        return match.group(1).replace("–", "-")

    def search(self, query: str, *, event_date: date, limit: int = 5) -> list[HybridSearchHit]:
        query = query.strip()
        if not query:
            raise ValueError("Hybrid search query cannot be empty")
        if limit < 1:
            raise ValueError("Hybrid search limit must be positive")

        query_embedding = self.embedding_provider.embed([query])[0]
        exact_article = self.extract_article_number(query)
        rows = self.repository.hybrid_search(
            query_text=query,
            embedding=query_embedding,
            event_date=event_date,
            exact_article=exact_article,
            limit=limit,
        )
        return [
            HybridSearchHit(
                norm=norm,
                semantic_score=semantic_score,
                lexical_score=lexical_score,
                exact_article_boost=exact_article_boost,
                total_score=total_score,
            )
            for norm, semantic_score, lexical_score, exact_article_boost, total_score in rows
        ]
