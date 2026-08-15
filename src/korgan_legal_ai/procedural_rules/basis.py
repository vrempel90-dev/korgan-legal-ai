from __future__ import annotations

from datetime import date

from korgan_legal_ai.domain.models import ResearchCitation, VerificationStatus
from korgan_legal_ai.procedural_rules.models import RuleBasis
from korgan_legal_ai.research.gateway import CitationGateway


class LegalBasisVerifier:
    """Verifies structured-rule legal bases through the fail-closed Citation Gateway."""

    def __init__(self, gateway: CitationGateway) -> None:
        self.gateway = gateway

    def verify(self, basis: RuleBasis, *, event_date: date) -> ResearchCitation | None:
        citations = self.gateway.research_locator(
            code_id=basis.code_id,
            article_number=basis.article_number,
            part=basis.part,
            point=basis.point,
            event_date=event_date.isoformat(),
        )
        if len(citations) != 1:
            return None
        citation = citations[0]
        if citation.status != VerificationStatus.VERIFIED:
            return None
        if citation.article != basis.locator:
            return None
        return citation
