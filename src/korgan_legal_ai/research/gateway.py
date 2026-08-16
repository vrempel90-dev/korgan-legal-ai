from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from urllib.parse import urlparse

from korgan_legal_ai.corpus.search import HybridSearchService
from korgan_legal_ai.domain.models import ResearchCitation, VerificationStatus


TRUSTED_KZ_DOMAINS = ("adilet.zan.kz", "zan.gov.kz", "gov.kz")


def is_trusted_official_url(source_url: str) -> bool:
    """Validate the hostname, never by substring matching."""
    try:
        parsed = urlparse(source_url)
    except ValueError:
        return False
    if parsed.scheme != "https" or not parsed.hostname:
        return False
    hostname = parsed.hostname.lower().rstrip(".")
    return any(hostname == domain or hostname.endswith(f".{domain}") for domain in TRUSTED_KZ_DOMAINS)


class LegalResearchBackend(ABC):
    @abstractmethod
    def verify(self, issue: str, *, event_date: str | None = None) -> list[ResearchCitation]:
        raise NotImplementedError

    def verify_locator(
        self, *, code_id: str, article_number: str, part: str = "", point: str = "",
        event_date: str | None = None,
    ) -> list[ResearchCitation]:
        return [
            ResearchCitation(
                source_title=f"{code_id} статья {article_number}",
                status=VerificationStatus.NEEDS_VERIFICATION,
                verification_note="This backend cannot verify a structured canonical locator.",
            )
        ]


class FailClosedResearchBackend(LegalResearchBackend):
    """Safe foundation backend: it never invents a citation when no verified corpus exists."""

    def verify(self, issue: str, *, event_date: str | None = None) -> list[ResearchCitation]:
        return [
            ResearchCitation(
                source_title=issue,
                status=VerificationStatus.NEEDS_VERIFICATION,
                verification_note=(
                    "No canonical Kazakhstan-law corpus is connected yet. Verify against an "
                    "official source before adding an exact article, rate, deadline or conclusion."
                ),
            )
        ]


class CanonicalHybridResearchBackend(LegalResearchBackend):
    EXACT_ARTICLE_MIN_TOTAL_SCORE = 1.0
    FREE_TEXT_MIN_TOTAL_SCORE = 0.72
    FREE_TEXT_MIN_SEMANTIC_SCORE = 0.55
    FREE_TEXT_MIN_MARGIN = 0.05

    def __init__(self, search: HybridSearchService) -> None:
        self.search = search

    @staticmethod
    def _needs(issue: str, reason: str) -> list[ResearchCitation]:
        return [ResearchCitation(
            source_title=issue,
            status=VerificationStatus.NEEDS_VERIFICATION,
            verification_note=reason,
        )]

    @staticmethod
    def _parse_event_date(raw: str | None) -> date | None:
        if not raw:
            return None
        try:
            return date.fromisoformat(raw)
        except ValueError:
            return None

    @staticmethod
    def _article_locator(article_number: str, part: str, point: str) -> str:
        locator = article_number
        if part:
            locator += f", часть {part}"
        if point:
            locator += f", пункт {point}"
        return locator

    @classmethod
    def _citation_for_norm(cls, norm, target_date: date, note: str) -> list[ResearchCitation]:
        if not is_trusted_official_url(norm.source_url):
            return cls._needs(norm.article_number, "Candidate source is not an allow-listed official Kazakhstan domain.")
        if not (norm.effective_from <= target_date and (norm.effective_to is None or norm.effective_to >= target_date)):
            return cls._needs(norm.article_number, "Candidate edition is not effective for the supplied event date.")
        article = cls._article_locator(norm.article_number, norm.part, norm.point)
        overdue = norm.review_overdue(target_date)
        if overdue:
            note = (
                f"{note} Плановая переверификация нормы просрочена с "
                f"{norm.next_review_date.isoformat()}."
            )
        return [ResearchCitation(
            source_url=norm.source_url,
            source_title=norm.title or norm.law_name or f"Статья {article}",
            law_name=norm.law_name,
            article=article,
            text_excerpt=norm.text,
            effective_from=norm.effective_from,
            effective_to=norm.effective_to,
            status=VerificationStatus.VERIFIED,
            verification_note=note,
            review_overdue=overdue,
            next_review_date=norm.next_review_date,
        )]

    def verify_locator(
        self, *, code_id: str, article_number: str, part: str = "", point: str = "",
        event_date: str | None = None,
    ) -> list[ResearchCitation]:
        target_date = self._parse_event_date(event_date)
        issue = f"{code_id} статья {self._article_locator(article_number, part, point)}"
        if target_date is None:
            return self._needs(issue, "Event date is required and must be ISO YYYY-MM-DD.")
        norm = self.search.repository.get_canonical_for_date(
            code_id=code_id, article_number=article_number, part=part, point=point,
            event_date=target_date,
        )
        if norm is None:
            return self._needs(issue, "Exact canonical locator is absent or not effective for the event date.")
        return self._citation_for_norm(
            norm, target_date,
            f"Verified by exact canonical locator for {target_date.isoformat()}; no semantic substitution allowed.",
        )

    def verify(self, issue: str, *, event_date: str | None = None) -> list[ResearchCitation]:
        target_date = self._parse_event_date(event_date)
        if target_date is None:
            return self._needs(
                issue,
                "Event date is required and must be ISO YYYY-MM-DD before an exact norm can be verified.",
            )
        try:
            hits = self.search.search(issue, event_date=target_date, limit=3)
        except (ValueError, IndexError):
            return self._needs(issue, "Hybrid search could not produce a verifiable candidate.")
        if not hits:
            return self._needs(issue, "No canonical, date-applicable norm matched the request.")

        requested_article = self.search.extract_article_number(issue)
        top = hits[0]
        if requested_article is not None:
            if top.norm.article_number != requested_article or top.exact_article_boost < 1.0:
                return self._needs(issue, f"Requested article {requested_article} was not found as an exact canonical match.")
            if top.total_score < self.EXACT_ARTICLE_MIN_TOTAL_SCORE:
                return self._needs(issue, "Exact article candidate did not clear the verification threshold.")
        else:
            runner_up_score = hits[1].total_score if len(hits) > 1 else 0.0
            margin = top.total_score - runner_up_score
            if (
                top.total_score < self.FREE_TEXT_MIN_TOTAL_SCORE
                or top.semantic_score < self.FREE_TEXT_MIN_SEMANTIC_SCORE
                or margin < self.FREE_TEXT_MIN_MARGIN
            ):
                return self._needs(
                    issue,
                    "Free-text candidate did not clear the conservative score and ranking-margin thresholds.",
                )
        return self._citation_for_norm(
            top.norm, target_date,
            f"Verified against canonical corpus for {target_date.isoformat()}; hybrid_score={top.total_score:.4f}.",
        )


class CitationGateway:
    def __init__(self, backend: LegalResearchBackend | None = None) -> None:
        self.backend = backend or FailClosedResearchBackend()

    @staticmethod
    def _validate(citations: list[ResearchCitation]) -> list[ResearchCitation]:
        for citation in citations:
            if citation.status == VerificationStatus.VERIFIED:
                if not citation.source_url:
                    raise ValueError("Verified citation must include source_url")
                if not is_trusted_official_url(citation.source_url):
                    raise ValueError("Verified citation must come from an approved official domain")
                if not citation.article or not citation.text_excerpt or citation.effective_from is None:
                    raise ValueError("Verified citation must include article, norm text and effective date")
        return citations

    def research(self, issue: str, *, event_date: str | None = None) -> list[ResearchCitation]:
        return self._validate(self.backend.verify(issue, event_date=event_date))

    def research_locator(
        self, *, code_id: str, article_number: str, part: str = "", point: str = "",
        event_date: str | None = None,
    ) -> list[ResearchCitation]:
        return self._validate(self.backend.verify_locator(
            code_id=code_id, article_number=article_number, part=part, point=point,
            event_date=event_date,
        ))
