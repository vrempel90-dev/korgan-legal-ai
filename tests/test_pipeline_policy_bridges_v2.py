from __future__ import annotations

import asyncio

from korgan.legal_types import LegalResearch, VerificationStatus
from korgan.pipeline_policy_bridges_v2 import (
    install_consultation_invariants_v2,
    install_finalized_policy_bridge_v2,
)
from korgan.research_balance_v2 import install_research_balance_v2


def _research(verified: list[str], unverified: list[str]) -> LegalResearch:
    return LegalResearch(
        status=VerificationStatus.NEEDS_VERIFICATION,
        applicable_law=[],
        procedural_requirements=[],
        verified_claims=verified,
        unverified_claims=unverified,
        source_urls=["https://example.test/source"] if verified else [],
        notes=[],
    )


def test_research_balance_retries_once_and_chooses_better_result() -> None:
    class FakeService:
        def __init__(self) -> None:
            self.calls = 0

        async def research_case(self, case_context: str, language: str = "ru") -> LegalResearch:
            self.calls += 1
            if self.calls == 1:
                return _research(["verified 1"], ["risk 1", "risk 2"])
            return _research(["verified 1", "verified 2"], ["risk 1"])

    install_research_balance_v2(FakeService)
    service = FakeService()
    result = asyncio.run(service.research_case("same input"))
    assert service.calls == 2
    assert len(result.verified_claims) == 2
    assert len(result.unverified_claims) == 1


def test_research_balance_does_not_repeat_good_first_pass() -> None:
    class GoodService:
        def __init__(self) -> None:
            self.calls = 0

        async def research_case(self, case_context: str, language: str = "ru") -> LegalResearch:
            self.calls += 1
            return _research(["verified 1", "verified 2"], ["risk 1"])

    install_research_balance_v2(GoodService)
    service = GoodService()
    result = asyncio.run(service.research_case("good input"))
    assert service.calls == 1
    assert len(result.verified_claims) >= len(result.unverified_claims)


def test_consultation_exposes_precise_article_without_source() -> None:
    class ConsultationService:
        async def consult(self, question: str, case_context: str = "", language: str = "ru"):
            return "Применяется статья 469 ГК РК.", []

    install_consultation_invariants_v2(ConsultationService)
    answer, urls = asyncio.run(ConsultationService().consult("вопрос"))
    assert urls == []
    assert "[СВЕРИТЬ:" in answer
    assert "source-bound" in answer


def test_finalized_stage_uses_same_scoped_policy_as_fast_stage() -> None:
    from korgan import document_quality
    from korgan import fast_professional_litigation as fast
    from korgan import finalized_litigation as finalized

    global_assess = document_quality.assess_document_quality
    install_finalized_policy_bridge_v2()
    assert finalized._dq.assess_document_quality is fast.assess_document_quality
    assert finalized._sp.deterministic_claim_preflight is fast.deterministic_claim_preflight
    # The bridge must remain scoped; independent QA modules are not monkeypatched.
    assert document_quality.assess_document_quality is global_assess
