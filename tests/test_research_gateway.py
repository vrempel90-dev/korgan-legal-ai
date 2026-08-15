import pytest

from korgan_legal_ai.domain.models import ResearchCitation, VerificationStatus
from korgan_legal_ai.research.gateway import CitationGateway, LegalResearchBackend


class BadBackend(LegalResearchBackend):
    def verify(self, issue: str, *, event_date: str | None = None):
        return [
            ResearchCitation(
                source_url="https://example.com/blog",
                source_title="Blog",
                article="123",
                status=VerificationStatus.VERIFIED,
            )
        ]


def test_default_gateway_fails_closed():
    citation = CitationGateway().research("Норма права")[0]
    assert citation.status == VerificationStatus.NEEDS_VERIFICATION
    assert citation.article is None


def test_untrusted_domain_cannot_be_verified():
    with pytest.raises(ValueError):
        CitationGateway(BadBackend()).research("Норма")
