from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field
from sqlalchemy import Engine, text

from korgan_legal_ai.corpus.embeddings import EmbeddingProvider
from korgan_legal_ai.research.gateway import is_trusted_official_url


class PracticeStatus(StrEnum):
    CANONICAL = "canonical"
    PENDING_REVIEW = "pending_review"


class JudicialAct(BaseModel):
    """One court decision held in the judicial-practice corpus.

    Practice is persuasive material, never authority. It can strengthen an argument a verified norm
    already supports; it can never make an unverified norm citable.
    """

    id: UUID = Field(default_factory=uuid4)
    case_number: str
    court_name: str
    decided_on: date
    instance: str
    legal_area: str
    summary: str
    text_excerpt: str
    source_url: str
    cited_articles: list[str] = Field(default_factory=list)
    retrieved_at: datetime | None = None
    status: PracticeStatus = PracticeStatus.PENDING_REVIEW
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None


@dataclass(frozen=True)
class PracticeHit:
    act: JudicialAct
    semantic_score: float
    lexical_score: float
    total_score: float


_COLUMNS = """
    id, case_number, court_name, decided_on, instance, legal_area, summary,
    text_excerpt, source_url, cited_articles, retrieved_at, status, reviewed_by, reviewed_at
"""

_UPSERT = text(
    f"""
    INSERT INTO judicial_practice (
        id, case_number, court_name, decided_on, instance, legal_area, summary,
        text_excerpt, source_url, cited_articles, status, reviewed_by, reviewed_at
    ) VALUES (
        :id, :case_number, :court_name, :decided_on, :instance, :legal_area, :summary,
        :text_excerpt, :source_url, :cited_articles, :status, :reviewed_by, :reviewed_at
    )
    ON CONFLICT (case_number, source_url) DO UPDATE SET
        court_name = EXCLUDED.court_name,
        decided_on = EXCLUDED.decided_on,
        instance = EXCLUDED.instance,
        legal_area = EXCLUDED.legal_area,
        summary = EXCLUDED.summary,
        text_excerpt = EXCLUDED.text_excerpt,
        cited_articles = EXCLUDED.cited_articles,
        status = EXCLUDED.status,
        reviewed_by = EXCLUDED.reviewed_by,
        reviewed_at = EXCLUDED.reviewed_at,
        retrieved_at = CURRENT_TIMESTAMP
    RETURNING id
    """
)


class JudicialPracticeRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    @staticmethod
    def _act_from_mapping(row: dict) -> JudicialAct:
        data = dict(row)
        data["status"] = PracticeStatus(data["status"])
        data["cited_articles"] = list(data.get("cited_articles") or [])
        return JudicialAct.model_validate(data)

    def upsert(self, act: JudicialAct) -> UUID:
        params = act.model_dump(mode="python")
        params["status"] = act.status.value
        params.pop("retrieved_at", None)
        with self.engine.begin() as connection:
            row = connection.execute(_UPSERT, params).one()
        return row.id

    def set_embedding(
        self,
        *,
        act_id: UUID,
        embedding: list[float],
        model: str,
        embedded_at: datetime,
    ) -> None:
        vector_text = "[" + ",".join(str(value) for value in embedding) + "]"
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    """
                    UPDATE judicial_practice
                    SET embedding = CAST(:embedding AS vector),
                        embedding_model = :model,
                        embedded_at = :embedded_at
                    WHERE id = :id
                    """
                ),
                {"embedding": vector_text, "model": model, "embedded_at": embedded_at, "id": act_id},
            )

    def hybrid_search(
        self,
        *,
        query_text: str,
        embedding: list[float],
        legal_area: str | None,
        limit: int,
    ) -> list[tuple[JudicialAct, float, float, float]]:
        """Semantic recall plus lexical precision over reviewed practice only.

        Acts still in ``pending_review`` are invisible to retrieval: an unreviewed decision must not
        reach a client document merely because it embedded well.
        """
        vector_text = "[" + ",".join(str(value) for value in embedding) + "]"
        query = text(
            f"""
            WITH scored AS (
                SELECT {_COLUMNS},
                       1 - (embedding <=> CAST(:embedding AS vector)) AS semantic_score,
                       ts_rank(
                           search_vector,
                           websearch_to_tsquery('russian'::regconfig, :query_text)
                       ) AS lexical_score
                FROM judicial_practice
                WHERE status = 'canonical'
                  AND embedding IS NOT NULL
                  AND (:legal_area IS NULL OR legal_area = :legal_area)
            )
            SELECT *, (semantic_score * 0.6 + LEAST(lexical_score, 1.0) * 0.4) AS total_score
            FROM scored
            ORDER BY total_score DESC
            LIMIT :limit
            """
        )
        with self.engine.connect() as connection:
            rows = (
                connection.execute(
                    query,
                    {
                        "embedding": vector_text,
                        "query_text": query_text,
                        "legal_area": legal_area,
                        "limit": limit,
                    },
                )
                .mappings()
                .all()
            )
        results: list[tuple[JudicialAct, float, float, float]] = []
        for row in rows:
            data = dict(row)
            semantic = float(data.pop("semantic_score"))
            lexical = float(data.pop("lexical_score"))
            total = float(data.pop("total_score"))
            results.append((self._act_from_mapping(data), semantic, lexical, total))
        return results


class JudicialPracticeService:
    """Fail-closed retrieval of supporting court practice.

    An empty or unreviewed corpus returns nothing at all. Nothing here can raise a verification
    status: practice is offered next to a verified norm, never in place of one.
    """

    MIN_TOTAL_SCORE = 0.68
    MIN_SEMANTIC_SCORE = 0.55

    def __init__(
        self,
        repository: JudicialPracticeRepository,
        embedding_provider: EmbeddingProvider,
    ) -> None:
        self.repository = repository
        self.embedding_provider = embedding_provider

    def search(
        self,
        query: str,
        *,
        legal_area: str | None = None,
        limit: int = 3,
    ) -> list[PracticeHit]:
        query = query.strip()
        if not query or limit < 1:
            return []
        try:
            embedding = self.embedding_provider.embed([query])[0]
            rows = self.repository.hybrid_search(
                query_text=query,
                embedding=embedding,
                legal_area=legal_area,
                limit=limit,
            )
        except Exception:
            # Practice is an enhancement. If retrieval is unavailable the document is produced
            # without it rather than failing, but nothing unverified is substituted either.
            return []

        hits: list[PracticeHit] = []
        for act, semantic, lexical, total in rows:
            if total < self.MIN_TOTAL_SCORE or semantic < self.MIN_SEMANTIC_SCORE:
                continue
            if not is_trusted_official_url(act.source_url):
                continue
            hits.append(
                PracticeHit(
                    act=act,
                    semantic_score=semantic,
                    lexical_score=lexical,
                    total_score=total,
                )
            )
        return hits
