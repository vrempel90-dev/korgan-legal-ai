"""Split the live legal service by document responsibility.

KORGAN production already has a broad stable service that owns consultations,
pre-trial documents, responses, contracts and inherited document helpers.  A
claim-quality upgrade must not replace that object wholesale.  This mux sends
only the two methods that form a court claim to the finalized litigation
service; everything else stays on the existing stable service.
"""

from __future__ import annotations

from typing import Any

from korgan.claim_pipeline_v2 import ClaimPipelineV2Adapter
from korgan.finalized_litigation import FinalizedProductionClaimService
from korgan.pretrial_response import PretrialResponseProductionService


class ClaimServiceMux:
    """Delegate claim research/drafting to ``claim`` and all other API to ``stable``."""

    def __init__(self, stable: Any, claim: Any):
        self.stable = stable
        self.claim = claim
        self.settings = stable.settings

    def __getattr__(self, name: str) -> Any:
        return getattr(self.stable, name)

    async def research_case(self, case_context: str, language: str = "ru"):
        return await self.claim.research_case(case_context, language=language)

    async def draft_claim(self, case_context: str, research: Any, language: str = "ru"):
        return await self.claim.draft_claim(case_context, research, language=language)


def build_strict_legal_service(settings: Any) -> ClaimPipelineV2Adapter:
    """Build the production service without changing non-claim document ownership."""
    stable = PretrialResponseProductionService(settings)
    claim = FinalizedProductionClaimService(settings)
    return ClaimPipelineV2Adapter(ClaimServiceMux(stable, claim))
