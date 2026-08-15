from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import Engine, text

from korgan_legal_ai.corpus.models import CorpusStatus, LegalNorm


_UPSERT = text(
    """
    INSERT INTO legal_norms (
        id, code_id, law_name, article_number, title, part, point, text,
        effective_from, effective_to, source_url, status,
        reviewed_by, reviewed_at
    ) VALUES (
        :id, :code_id, :law_name, :article_number, :title, :part, :point, :text,
        :effective_from, :effective_to, :source_url, :status,
        :reviewed_by, :reviewed_at
    )
    ON CONFLICT (
        code_id, article_number, part, point, effective_from, source_url
    ) DO UPDATE SET
        law_name = EXCLUDED.law_name,
        title = EXCLUDED.title,
        text = EXCLUDED.text,
        effective_to = EXCLUDED.effective_to,
        status = EXCLUDED.status,
        reviewed_by = EXCLUDED.reviewed_by,
        reviewed_at = EXCLUDED.reviewed_at,
        retrieved_at = CURRENT_TIMESTAMP
    RETURNING id
    """
)


class LegalNormRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    @staticmethod
    def _norm_from_mapping(row: dict) -> LegalNorm:
        data = dict(row)
        data["status"] = CorpusStatus(data["status"])
        return LegalNorm.model_validate(data)

    def upsert(self, norm: LegalNorm) -> UUID:
        params = norm.model_dump(mode="python")
        params["status"] = norm.status.value
        with self.engine.begin() as connection:
            row = connection.execute(_UPSERT, params).one()
        return row.id

    def get_canonical_for_date(
        self,
        *,
        code_id: str,
        article_number: str,
        event_date: date,
        part: str = "",
        point: str = "",
    ) -> LegalNorm | None:
        query = text(
            """
            SELECT id, code_id, law_name, article_number, title, part, point, text,
                   effective_from, effective_to, source_url, retrieved_at,
                   status, reviewed_by, reviewed_at
            FROM legal_norms
            WHERE code_id = :code_id
              AND article_number = :article_number
              AND part = :part
              AND point = :point
              AND status = 'canonical'
              AND effective_from <= :event_date
              AND (effective_to IS NULL OR effective_to >= :event_date)
            ORDER BY effective_from DESC
            LIMIT 1
            """
        )
        with self.engine.connect() as connection:
            row = connection.execute(
                query,
                {
                    "code_id": code_id,
                    "article_number": article_number,
                    "part": part,
                    "point": point,
                    "event_date": event_date,
                },
            ).mappings().first()
        if row is None:
            return None
        return self._norm_from_mapping(dict(row))

    def get_by_locator(
        self,
        *,
        code_id: str,
        article_number: str,
        part: str = "",
        point: str = "",
    ) -> list[LegalNorm]:
        query = text(
            """
            SELECT id, code_id, law_name, article_number, title, part, point, text,
                   effective_from, effective_to, source_url, retrieved_at,
                   status, reviewed_by, reviewed_at
            FROM legal_norms
            WHERE code_id = :code_id AND article_number = :article_number
              AND part = :part AND point = :point
            ORDER BY effective_from DESC
            """
        )
        with self.engine.connect() as connection:
            rows = connection.execute(
                query,
                {"code_id": code_id, "article_number": article_number, "part": part, "point": point},
            ).mappings().all()
        return [self._norm_from_mapping(dict(row)) for row in rows]

    def list_canonical_missing_embeddings(self, *, limit: int = 100) -> list[LegalNorm]:
        query = text(
            """
            SELECT id, code_id, law_name, article_number, title, part, point, text,
                   effective_from, effective_to, source_url, retrieved_at,
                   status, reviewed_by, reviewed_at
            FROM legal_norms
            WHERE status = 'canonical' AND embedding IS NULL
            ORDER BY code_id, article_number, part, point, effective_from
            LIMIT :limit
            """
        )
        with self.engine.connect() as connection:
            rows = connection.execute(query, {"limit": limit}).mappings().all()
        return [self._norm_from_mapping(dict(row)) for row in rows]

    def set_embedding(
        self,
        *,
        norm_id: UUID,
        embedding: list[float],
        model: str,
        embedded_at: datetime,
    ) -> None:
        vector_text = "[" + ",".join(str(value) for value in embedding) + "]"
        query = text(
            """
            UPDATE legal_norms
            SET embedding = CAST(:embedding AS vector),
                embedding_model = :model,
                embedded_at = :embedded_at
            WHERE id = :id
            """
        )
        with self.engine.begin() as connection:
            connection.execute(
                query,
                {"embedding": vector_text, "model": model, "embedded_at": embedded_at, "id": norm_id},
            )

    def semantic_search(
        self,
        *,
        embedding: list[float],
        event_date: date,
        limit: int = 5,
    ) -> list[tuple[LegalNorm, float]]:
        vector_text = "[" + ",".join(str(value) for value in embedding) + "]"
        query = text(
            """
            SELECT id, code_id, law_name, article_number, title, part, point, text,
                   effective_from, effective_to, source_url, retrieved_at,
                   status, reviewed_by, reviewed_at,
                   1 - (embedding <=> CAST(:embedding AS vector)) AS score
            FROM legal_norms
            WHERE status = 'canonical'
              AND embedding IS NOT NULL
              AND effective_from <= :event_date
              AND (effective_to IS NULL OR effective_to >= :event_date)
            ORDER BY embedding <=> CAST(:embedding AS vector)
            LIMIT :limit
            """
        )
        with self.engine.connect() as connection:
            rows = connection.execute(
                query,
                {"embedding": vector_text, "event_date": event_date, "limit": limit},
            ).mappings().all()
        result: list[tuple[LegalNorm, float]] = []
        for row in rows:
            data = dict(row)
            score = float(data.pop("score"))
            result.append((self._norm_from_mapping(data), score))
        return result

    def hybrid_search(
        self,
        *,
        query_text: str,
        embedding: list[float],
        event_date: date,
        exact_article: str | None,
        limit: int = 5,
    ) -> list[tuple[LegalNorm, float, float, float, float]]:
        """Combine semantic recall with weighted FTS and deterministic locator boost.

        Exact article locators receive +1.0, which intentionally dominates the
        normalized semantic/lexical blend. Only canonical and date-applicable rows
        participate; pending_review rows can never leak through this method.
        """
        vector_text = "[" + ",".join(str(value) for value in embedding) + "]"
        query = text(
            """
            WITH scored AS (
                SELECT id, code_id, law_name, article_number, title, part, point, text,
                       effective_from, effective_to, source_url, retrieved_at,
                       status, reviewed_by, reviewed_at,
                       GREATEST(0.0, 1 - (embedding <=> CAST(:embedding AS vector))) AS semantic_score,
                       ts_rank_cd(
                           search_vector,
                           websearch_to_tsquery('russian'::regconfig, :query_text),
                           32
                       ) AS lexical_score,
                       CASE
                           WHEN CAST(:exact_article AS text) IS NOT NULL
                                AND article_number = CAST(:exact_article AS text) THEN 1.0
                           ELSE 0.0
                       END AS exact_article_boost
                FROM legal_norms
                WHERE status = 'canonical'
                  AND embedding IS NOT NULL
                  AND effective_from <= :event_date
                  AND (effective_to IS NULL OR effective_to >= :event_date)
            )
            SELECT *,
                   (0.55 * semantic_score) +
                   (0.35 * LEAST(lexical_score, 1.0)) +
                   exact_article_boost AS total_score
            FROM scored
            ORDER BY total_score DESC, effective_from DESC, article_number
            LIMIT :limit
            """
        )
        params = {
            "query_text": query_text,
            "embedding": vector_text,
            "event_date": event_date,
            "exact_article": exact_article,
            "limit": limit,
        }
        with self.engine.connect() as connection:
            rows = connection.execute(query, params).mappings().all()

        result: list[tuple[LegalNorm, float, float, float, float]] = []
        for row in rows:
            data = dict(row)
            semantic_score = float(data.pop("semantic_score"))
            lexical_score = float(data.pop("lexical_score"))
            exact_article_boost = float(data.pop("exact_article_boost"))
            total_score = float(data.pop("total_score"))
            result.append(
                (
                    self._norm_from_mapping(data),
                    semantic_score,
                    lexical_score,
                    exact_article_boost,
                    total_score,
                )
            )
        return result

    def count(self) -> int:
        with self.engine.connect() as connection:
            return int(connection.execute(text("SELECT count(*) FROM legal_norms")).scalar_one())
