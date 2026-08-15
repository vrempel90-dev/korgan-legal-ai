from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Sequence

from korgan_legal_ai.corpus.models import LegalNorm
from korgan_legal_ai.corpus.repository import LegalNormRepository

EMBEDDING_DIMENSIONS = 3072
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-large"


class EmbeddingProvider(ABC):
    @property
    @abstractmethod
    def model(self) -> str: ...

    @abstractmethod
    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class OpenAIEmbeddingProvider(EmbeddingProvider):
    def __init__(
        self,
        *,
        api_key: str,
        model: str = DEFAULT_EMBEDDING_MODEL,
        dimensions: int = EMBEDDING_DIMENSIONS,
    ) -> None:
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required for live embedding generation")
        self._model = model
        self._dimensions = dimensions
        from openai import OpenAI
        self._client = OpenAI(api_key=api_key)

    @property
    def model(self) -> str:
        return self._model

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        response = self._client.embeddings.create(
            model=self._model,
            input=list(texts),
            dimensions=self._dimensions,
        )
        ordered = sorted(response.data, key=lambda item: item.index)
        vectors = [item.embedding for item in ordered]
        if any(len(vector) != self._dimensions for vector in vectors):
            raise ValueError("Embedding provider returned an unexpected vector dimension")
        return vectors


@dataclass(frozen=True)
class IndexingResult:
    indexed: int
    model: str


class CorpusEmbeddingIndexer:
    """One legal norm row is one embedding chunk; no token-based splitting is allowed."""

    def __init__(self, repository: LegalNormRepository, provider: EmbeddingProvider) -> None:
        self.repository = repository
        self.provider = provider

    @staticmethod
    def chunk_text(norm: LegalNorm) -> str:
        locator = f"Статья {norm.article_number}"
        if norm.part:
            locator += f", часть {norm.part}"
        if norm.point:
            locator += f", пункт {norm.point}"
        title = f". {norm.title}" if norm.title else ""
        law = f"{norm.law_name}. " if norm.law_name else ""
        return f"{law}{locator}{title}\n{norm.text}".strip()

    def index_missing_canonical(self, *, batch_size: int = 64) -> IndexingResult:
        norms = self.repository.list_canonical_missing_embeddings(limit=batch_size)
        if not norms:
            return IndexingResult(indexed=0, model=self.provider.model)
        chunks = [self.chunk_text(norm) for norm in norms]
        vectors = self.provider.embed(chunks)
        if len(vectors) != len(norms):
            raise ValueError("Embedding provider returned an unexpected result count")
        now = datetime.now(timezone.utc)
        for norm, vector in zip(norms, vectors, strict=True):
            self.repository.set_embedding(
                norm_id=norm.id,
                embedding=vector,
                model=self.provider.model,
                embedded_at=now,
            )
        return IndexingResult(indexed=len(norms), model=self.provider.model)
