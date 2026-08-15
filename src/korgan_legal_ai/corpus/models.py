from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator


class CorpusStatus(StrEnum):
    CANONICAL = "canonical"
    PENDING_REVIEW = "pending_review"


class LegalNorm(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    code_id: str
    law_name: str | None = None
    article_number: str
    title: str | None = None
    part: str = ""
    point: str = ""
    text: str
    effective_from: date
    effective_to: date | None = None
    source_url: str
    retrieved_at: datetime | None = None
    status: CorpusStatus
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None

    @model_validator(mode="after")
    def validate_range(self) -> "LegalNorm":
        if self.effective_to is not None and self.effective_to < self.effective_from:
            raise ValueError("effective_to cannot precede effective_from")
        return self
