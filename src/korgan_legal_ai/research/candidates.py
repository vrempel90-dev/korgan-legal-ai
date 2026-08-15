from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import Engine, text


class CandidateStatus(StrEnum):
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"


class ResearchCandidate(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    query_text: str
    requested_event_date: date | None = None
    code_id: str | None = None
    law_name: str | None = None
    article_number: str
    part: str = ""
    point: str = ""
    title: str | None = None
    text: str
    proposed_effective_from: date | None = None
    proposed_effective_to: date | None = None
    source_url: str
    retrieved_at: datetime | None = None
    status: CandidateStatus = CandidateStatus.PENDING_REVIEW
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    review_note: str | None = None
    canonical_norm_id: UUID | None = None

    @model_validator(mode="after")
    def validate_state(self) -> "ResearchCandidate":
        if (
            self.proposed_effective_from is not None
            and self.proposed_effective_to is not None
            and self.proposed_effective_to < self.proposed_effective_from
        ):
            raise ValueError("proposed_effective_to cannot precede proposed_effective_from")
        if self.status == CandidateStatus.PENDING_REVIEW:
            if self.reviewed_by is not None or self.reviewed_at is not None or self.canonical_norm_id is not None:
                raise ValueError("pending_review candidate cannot carry completed review metadata")
        elif self.status == CandidateStatus.APPROVED:
            if not self.reviewed_by or self.reviewed_at is None or self.canonical_norm_id is None:
                raise ValueError("approved candidate requires reviewer, timestamp and canonical norm id")
        elif self.status == CandidateStatus.REJECTED:
            if not self.reviewed_by or self.reviewed_at is None or self.canonical_norm_id is not None:
                raise ValueError("rejected candidate requires reviewer/timestamp and no canonical norm id")
        return self


class PendingReviewCandidate(ResearchCandidate):
    status: Literal[CandidateStatus.PENDING_REVIEW] = CandidateStatus.PENDING_REVIEW


class LawyerReviewCard(BaseModel):
    candidate_id: UUID
    query_text: str
    article_number: str
    law_name: str | None = None
    title: str | None = None
    text: str
    source_url: str
    proposed_effective_from: date | None = None
    proposed_effective_to: date | None = None
    proposed_status: Literal["pending_review"] = "pending_review"


_RETURNING = """
    id, query_text, requested_event_date, code_id, law_name,
    article_number, part, point, title, text,
    proposed_effective_from, proposed_effective_to, source_url,
    retrieved_at, status, reviewed_by, reviewed_at, review_note, canonical_norm_id
"""

_UPSERT = text(
    f"""
    INSERT INTO legal_research_candidates (
        id, query_text, requested_event_date, code_id, law_name,
        article_number, part, point, title, text,
        proposed_effective_from, proposed_effective_to, source_url, status
    ) VALUES (
        :id, :query_text, :requested_event_date, :code_id, :law_name,
        :article_number, :part, :point, :title, :text,
        :proposed_effective_from, :proposed_effective_to, :source_url, :status
    )
    ON CONFLICT (source_url, article_number, part, point)
    DO UPDATE SET
        query_text = EXCLUDED.query_text,
        requested_event_date = EXCLUDED.requested_event_date,
        code_id = EXCLUDED.code_id,
        law_name = EXCLUDED.law_name,
        title = EXCLUDED.title,
        text = EXCLUDED.text,
        proposed_effective_from = EXCLUDED.proposed_effective_from,
        proposed_effective_to = EXCLUDED.proposed_effective_to,
        retrieved_at = CURRENT_TIMESTAMP
    WHERE legal_research_candidates.status = 'pending_review'
    RETURNING {_RETURNING}
    """
)


class ResearchCandidateRepository:
    """Untrusted discoveries live here, physically separate from canonical legal_norms."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    @staticmethod
    def _from_row(row: dict) -> ResearchCandidate:
        data = dict(row)
        data["status"] = CandidateStatus(data["status"])
        return ResearchCandidate.model_validate(data)

    def upsert_pending(self, candidate: PendingReviewCandidate) -> ResearchCandidate:
        params = candidate.model_dump(mode="python")
        params["status"] = CandidateStatus.PENDING_REVIEW.value
        with self.engine.begin() as connection:
            row = connection.execute(_UPSERT, params).mappings().first()
            if row is None:
                row = connection.execute(
                    text(
                        f"""
                        SELECT {_RETURNING}
                        FROM legal_research_candidates
                        WHERE source_url=:source_url
                          AND article_number=:article_number
                          AND part=:part AND point=:point
                        """
                    ),
                    {
                        "source_url": candidate.source_url,
                        "article_number": candidate.article_number,
                        "part": candidate.part,
                        "point": candidate.point,
                    },
                ).mappings().one()
        return self._from_row(dict(row))

    def get_by_id(self, candidate_id: UUID) -> ResearchCandidate | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                text(f"SELECT {_RETURNING} FROM legal_research_candidates WHERE id=:id"),
                {"id": candidate_id},
            ).mappings().first()
        return self._from_row(dict(row)) if row is not None else None

    def list_pending(self, *, limit: int = 100) -> list[ResearchCandidate]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    f"""
                    SELECT {_RETURNING}
                    FROM legal_research_candidates
                    WHERE status='pending_review'
                    ORDER BY retrieved_at ASC
                    LIMIT :limit
                    """
                ),
                {"limit": limit},
            ).mappings().all()
        return [self._from_row(dict(row)) for row in rows]

    def get_pending_by_article(self, article_number: str) -> list[ResearchCandidate]:
        query = text(
            f"""
            SELECT {_RETURNING}
            FROM legal_research_candidates
            WHERE status='pending_review' AND article_number=:article_number
            ORDER BY retrieved_at DESC
            """
        )
        with self.engine.connect() as connection:
            rows = connection.execute(query, {"article_number": article_number}).mappings().all()
        return [self._from_row(dict(row)) for row in rows]

    def mark_rejected(
        self,
        candidate_id: UUID,
        *,
        reviewed_by: str,
        reviewed_at: datetime,
        review_note: str,
    ) -> ResearchCandidate:
        if not reviewed_by.strip() or not review_note.strip():
            raise ValueError("reviewed_by and rejection reason are required")
        with self.engine.begin() as connection:
            row = connection.execute(
                text(
                    f"""
                    UPDATE legal_research_candidates
                    SET status='rejected', reviewed_by=:reviewed_by,
                        reviewed_at=:reviewed_at, review_note=:review_note,
                        canonical_norm_id=NULL
                    WHERE id=:id AND status='pending_review'
                    RETURNING {_RETURNING}
                    """
                ),
                {
                    "id": candidate_id,
                    "reviewed_by": reviewed_by.strip(),
                    "reviewed_at": reviewed_at,
                    "review_note": review_note.strip(),
                },
            ).mappings().first()
        if row is None:
            raise ValueError("candidate does not exist or is no longer pending_review")
        return self._from_row(dict(row))

    def count_pending(self) -> int:
        with self.engine.connect() as connection:
            return int(
                connection.execute(
                    text("SELECT count(*) FROM legal_research_candidates WHERE status='pending_review'")
                ).scalar_one()
            )
