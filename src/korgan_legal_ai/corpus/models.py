from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator


class CorpusStatus(StrEnum):
    CANONICAL = "canonical"
    PENDING_REVIEW = "pending_review"


DEFAULT_REVIEW_MONTHS = 6


def default_next_review(from_date: date, *, months: int = DEFAULT_REVIEW_MONTHS) -> date:
    """The date a norm should next be re-checked against the official source.

    Calendar arithmetic, clamped to the last valid day of the target month so that adding six
    months to 31 August does not overflow into September.
    """
    month_index = from_date.month - 1 + months
    year = from_date.year + month_index // 12
    month = month_index % 12 + 1
    last_day = [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
                31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1]
    return date(year, month, min(from_date.day, last_day))


class LegalNorm(BaseModel):
    """One article-level entry of the canonical corpus.

    ``reviewed_by`` and ``reviewed_at`` are the provenance of verification: who confirmed this
    wording against the official source, and when. There is deliberately no second verified_by /
    verified_at pair — one mechanism, so a record cannot be verified in one field and unverified in
    another.
    """

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
    # Document types this norm is relevant to, by blueprint document-type value. Empty means the
    # norm has not been scoped yet; it is used for coverage reporting and navigation, never to hide
    # a norm from retrieval, because a wrong scope would silently narrow the law.
    applicable_document_types: list[str] = Field(default_factory=list)
    # When this wording should be re-checked against the official source. A passed date does not
    # invalidate the norm; it marks it as due for re-verification and surfaces a warning.
    next_review_date: date | None = None

    @model_validator(mode="after")
    def validate_range(self) -> "LegalNorm":
        if self.effective_to is not None and self.effective_to < self.effective_from:
            raise ValueError("effective_to cannot precede effective_from")
        return self

    def review_overdue(self, as_of: date) -> bool:
        return self.next_review_date is not None and self.next_review_date < as_of
