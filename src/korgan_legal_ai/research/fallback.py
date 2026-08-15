from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from typing import Sequence

from pydantic import BaseModel, model_validator

from korgan_legal_ai.corpus.search import HybridSearchService
from korgan_legal_ai.domain.models import ResearchCitation, VerificationStatus
from korgan_legal_ai.research.candidates import (
    CandidateStatus,
    LawyerReviewCard,
    PendingReviewCandidate,
    ResearchCandidateRepository,
)
from korgan_legal_ai.research.gateway import CitationGateway, TRUSTED_KZ_DOMAINS, is_trusted_official_url


class DiscoveredOfficialNorm(BaseModel):
    code_id: str | None = None
    law_name: str | None = None
    article_number: str
    part: str = ""
    point: str = ""
    title: str | None = None
    text: str
    source_url: str
    effective_from: date | None = None
    effective_to: date | None = None


class OfficialFallbackSearchResult(BaseModel):
    found: bool
    candidate: DiscoveredOfficialNorm | None = None
    note: str | None = None

    @model_validator(mode="after")
    def candidate_required_when_found(self) -> "OfficialFallbackSearchResult":
        if self.found and self.candidate is None:
            raise ValueError("candidate is required when found=true")
        return self


class OfficialSearchProvider(ABC):
    @abstractmethod
    def search(self, issue: str, *, event_date: date | None) -> OfficialFallbackSearchResult:
        raise NotImplementedError


class OpenAIOfficialSearchProvider(OfficialSearchProvider):
    """Discovery-only web search hard-filtered to official Kazakhstan domains."""

    def __init__(self, *, api_key: str, model: str = "gpt-5-mini") -> None:
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required for live official fallback")
        from openai import OpenAI

        self.client = OpenAI(api_key=api_key)
        self.model = model

    def search(self, issue: str, *, event_date: date | None) -> OfficialFallbackSearchResult:
        event_date_text = event_date.isoformat() if event_date else "not supplied"
        response = self.client.responses.parse(
            model=self.model,
            tools=[
                {
                    "type": "web_search",
                    "filters": {"allowed_domains": list(TRUSTED_KZ_DOMAINS)},
                    "search_context_size": "medium",
                }
            ],
            input=[
                {
                    "role": "system",
                    "content": (
                        "You are a discovery-only Kazakhstan legal researcher. You MUST use web search. "
                        "Search only the allowed official domains supplied by the tool. Find the exact "
                        "requested legal article, not a merely similar provision. Copy the norm text from "
                        "the official source. Never infer or invent an effective date: use null if the "
                        "source material available to you does not establish it. Never claim that a result "
                        "is canonical or verified; it is only a candidate for lawyer review. If the exact "
                        "article and official source cannot be established, return found=false."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Research request: {issue}\nEvent date: {event_date_text}",
                },
            ],
            text_format=OfficialFallbackSearchResult,
        )
        parsed = response.output_parsed
        if parsed is None:
            return OfficialFallbackSearchResult(found=False, note="No structured fallback result")
        return parsed


class OfficialFallbackService:
    def __init__(
        self,
        provider: OfficialSearchProvider,
        repository: ResearchCandidateRepository,
    ) -> None:
        self.provider = provider
        self.repository = repository

    def discover_and_stage(self, issue: str, *, event_date: date | None) -> LawyerReviewCard | None:
        result = self.provider.search(issue, event_date=event_date)
        if not result.found or result.candidate is None:
            return None

        discovered = result.candidate
        requested_article = HybridSearchService.extract_article_number(issue)
        if requested_article is not None and discovered.article_number != requested_article:
            return None
        if not is_trusted_official_url(discovered.source_url):
            return None
        if not discovered.text.strip() or not discovered.article_number.strip():
            return None

        staged = self.repository.upsert_pending(
            PendingReviewCandidate(
                query_text=issue,
                requested_event_date=event_date,
                code_id=discovered.code_id,
                law_name=discovered.law_name,
                article_number=discovered.article_number,
                part=discovered.part,
                point=discovered.point,
                title=discovered.title,
                text=discovered.text,
                proposed_effective_from=discovered.effective_from,
                proposed_effective_to=discovered.effective_to,
                source_url=discovered.source_url,
            )
        )
        # A rejected candidate is never silently reopened by another web search.
        # An approved candidate should already be served by the canonical gateway.
        if staged.status != CandidateStatus.PENDING_REVIEW:
            return None
        return LawyerReviewCard(
            candidate_id=staged.id,
            query_text=staged.query_text,
            article_number=staged.article_number,
            law_name=staged.law_name,
            title=staged.title,
            text=staged.text,
            source_url=staged.source_url,
            proposed_effective_from=staged.proposed_effective_from,
            proposed_effective_to=staged.proposed_effective_to,
        )


@dataclass(frozen=True)
class FallbackResearchOutcome:
    citations: Sequence[ResearchCitation]
    review_card: LawyerReviewCard | None


class FallbackCitationGateway:
    """Runs official discovery only after the canonical gateway fails closed.

    A fallback candidate can never become a VERIFIED user citation here. Even when
    staged successfully, the returned user-facing citation remains NEEDS_VERIFICATION.
    """

    def __init__(self, primary: CitationGateway, fallback: OfficialFallbackService) -> None:
        self.primary = primary
        self.fallback = fallback

    @staticmethod
    def _parse_date(raw: str | None) -> date | None:
        if not raw:
            return None
        try:
            return date.fromisoformat(raw)
        except ValueError:
            return None

    def research(self, issue: str, *, event_date: str | None = None) -> FallbackResearchOutcome:
        primary = self.primary.research(issue, event_date=event_date)
        if any(citation.status == VerificationStatus.VERIFIED for citation in primary):
            return FallbackResearchOutcome(citations=primary, review_card=None)

        card = self.fallback.discover_and_stage(issue, event_date=self._parse_date(event_date))
        if card is None:
            return FallbackResearchOutcome(citations=primary, review_card=None)

        user_result = ResearchCitation(
            source_title=issue,
            status=VerificationStatus.NEEDS_VERIFICATION,
            verification_note=(
                "Найден кандидат на официальном источнике и сохранен как pending_review; "
                "до ручного подтверждения юристом точная норма не считается VERIFIED."
            ),
        )
        return FallbackResearchOutcome(citations=[user_result], review_card=card)
