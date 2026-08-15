from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import text

from korgan_legal_ai.corpus.embeddings import EMBEDDING_DIMENSIONS, CorpusEmbeddingIndexer, EmbeddingProvider
from korgan_legal_ai.corpus.models import CorpusStatus, LegalNorm
from korgan_legal_ai.corpus.repository import LegalNormRepository
from korgan_legal_ai.research.candidates import (
    CandidateStatus,
    ResearchCandidate,
    ResearchCandidateRepository,
)
from korgan_legal_ai.research.gateway import is_trusted_official_url


class ApprovalResult(BaseModel):
    candidate_id: UUID
    canonical_norm_id: UUID
    article_number: str
    status: CandidateStatus = CandidateStatus.APPROVED


class RejectionResult(BaseModel):
    candidate_id: UUID
    article_number: str
    status: CandidateStatus = CandidateStatus.REJECTED


_LOCK_CANDIDATE = text(
    """
    SELECT id, query_text, requested_event_date, code_id, law_name,
           article_number, part, point, title, text,
           proposed_effective_from, proposed_effective_to, source_url,
           retrieved_at, status, reviewed_by, reviewed_at, review_note, canonical_norm_id
    FROM legal_research_candidates
    WHERE id=:id
    FOR UPDATE
    """
)

_PROMOTE_CANONICAL = text(
    """
    INSERT INTO legal_norms (
        id, code_id, law_name, article_number, title, part, point, text,
        effective_from, effective_to, source_url, status,
        reviewed_by, reviewed_at, embedding, embedding_model, embedded_at
    ) VALUES (
        :id, :code_id, :law_name, :article_number, :title, :part, :point, :text,
        :effective_from, :effective_to, :source_url, 'canonical',
        :reviewed_by, :reviewed_at, CAST(:embedding AS vector), :embedding_model, :embedded_at
    )
    ON CONFLICT (code_id, article_number, part, point, effective_from, source_url)
    DO UPDATE SET
        law_name=EXCLUDED.law_name,
        title=EXCLUDED.title,
        text=EXCLUDED.text,
        effective_to=EXCLUDED.effective_to,
        status='canonical',
        reviewed_by=EXCLUDED.reviewed_by,
        reviewed_at=EXCLUDED.reviewed_at,
        retrieved_at=CURRENT_TIMESTAMP,
        embedding=EXCLUDED.embedding,
        embedding_model=EXCLUDED.embedding_model,
        embedded_at=EXCLUDED.embedded_at
    RETURNING id
    """
)


class LawyerReviewService:
    """Explicit human approval/rejection gate for discovery-only fallback candidates."""

    def __init__(
        self,
        candidate_repository: ResearchCandidateRepository,
        norm_repository: LegalNormRepository,
        embedding_provider: EmbeddingProvider,
    ) -> None:
        if candidate_repository.engine is not norm_repository.engine:
            raise ValueError("candidate and canonical repositories must share the same database engine")
        self.candidates = candidate_repository
        self.norms = norm_repository
        self.embedding_provider = embedding_provider

    @staticmethod
    def _critical_snapshot(candidate: ResearchCandidate) -> tuple[object, ...]:
        return (
            candidate.status,
            candidate.code_id,
            candidate.law_name,
            candidate.article_number,
            candidate.part,
            candidate.point,
            candidate.title,
            candidate.text,
            candidate.proposed_effective_from,
            candidate.proposed_effective_to,
            candidate.source_url,
        )

    def approve(
        self,
        candidate_id: UUID,
        *,
        reviewed_by: str,
        effective_from: date | None = None,
        effective_to: date | None = None,
        code_id: str | None = None,
        law_name: str | None = None,
        review_note: str | None = None,
    ) -> ApprovalResult:
        if not reviewed_by.strip():
            raise ValueError("reviewed_by is required")
        candidate = self.candidates.get_by_id(candidate_id)
        if candidate is None or candidate.status != CandidateStatus.PENDING_REVIEW:
            raise ValueError("candidate does not exist or is no longer pending_review")
        if not is_trusted_official_url(candidate.source_url):
            raise ValueError("candidate source is not an allow-listed official Kazakhstan URL")

        final_effective_from = effective_from or candidate.proposed_effective_from
        final_effective_to = effective_to if effective_to is not None else candidate.proposed_effective_to
        final_code_id = (code_id or candidate.code_id or "").strip()
        final_law_name = (law_name or candidate.law_name or "").strip()
        if final_effective_from is None:
            raise ValueError("effective_from must be explicitly established before canonical approval")
        if not final_code_id:
            raise ValueError("code_id must be explicitly established before canonical approval")
        if not final_law_name:
            raise ValueError("law_name must be explicitly established before canonical approval")

        reviewed_at = datetime.now(timezone.utc)
        norm = LegalNorm(
            code_id=final_code_id,
            law_name=final_law_name,
            article_number=candidate.article_number,
            title=candidate.title,
            part=candidate.part,
            point=candidate.point,
            text=candidate.text,
            effective_from=final_effective_from,
            effective_to=final_effective_to,
            source_url=candidate.source_url,
            status=CorpusStatus.CANONICAL,
            reviewed_by=reviewed_by.strip(),
            reviewed_at=reviewed_at,
        )
        vector = self.embedding_provider.embed([CorpusEmbeddingIndexer.chunk_text(norm)])
        if len(vector) != 1 or len(vector[0]) != EMBEDDING_DIMENSIONS:
            raise ValueError("approval embedding must contain exactly one 3072-dimensional vector")
        vector_text = "[" + ",".join(str(value) for value in vector[0]) + "]"

        with self.candidates.engine.begin() as connection:
            locked_row = connection.execute(_LOCK_CANDIDATE, {"id": candidate_id}).mappings().first()
            if locked_row is None:
                raise ValueError("candidate disappeared during review")
            locked_data = dict(locked_row)
            locked_data["status"] = CandidateStatus(locked_data["status"])
            locked = ResearchCandidate.model_validate(locked_data)
            if locked.status != CandidateStatus.PENDING_REVIEW:
                raise ValueError("candidate is no longer pending_review")
            if self._critical_snapshot(locked) != self._critical_snapshot(candidate):
                raise ValueError("candidate changed during review; reload it before approving")

            params = norm.model_dump(mode="python")
            params.update(
                {
                    "embedding": vector_text,
                    "embedding_model": self.embedding_provider.model,
                    "embedded_at": reviewed_at,
                    "reviewed_by": reviewed_by.strip(),
                    "reviewed_at": reviewed_at,
                }
            )
            canonical_norm_id = connection.execute(_PROMOTE_CANONICAL, params).scalar_one()
            updated = connection.execute(
                text(
                    """
                    UPDATE legal_research_candidates
                    SET status='approved', reviewed_by=:reviewed_by,
                        reviewed_at=:reviewed_at, review_note=:review_note,
                        canonical_norm_id=:canonical_norm_id
                    WHERE id=:id AND status='pending_review'
                    """
                ),
                {
                    "id": candidate_id,
                    "reviewed_by": reviewed_by.strip(),
                    "reviewed_at": reviewed_at,
                    "review_note": review_note.strip() if review_note else None,
                    "canonical_norm_id": canonical_norm_id,
                },
            )
            if updated.rowcount != 1:
                raise RuntimeError("atomic candidate approval failed")

        return ApprovalResult(
            candidate_id=candidate_id,
            canonical_norm_id=canonical_norm_id,
            article_number=norm.article_number,
        )

    def reject(
        self,
        candidate_id: UUID,
        *,
        reviewed_by: str,
        reason: str,
    ) -> RejectionResult:
        candidate = self.candidates.get_by_id(candidate_id)
        if candidate is None:
            raise ValueError("candidate does not exist")
        rejected = self.candidates.mark_rejected(
            candidate_id,
            reviewed_by=reviewed_by,
            reviewed_at=datetime.now(timezone.utc),
            review_note=reason,
        )
        return RejectionResult(candidate_id=rejected.id, article_number=rejected.article_number)
