"""Split the live legal service by document responsibility.

KORGAN production already has a broad stable service that owns consultations,
pre-trial documents, responses, contracts and inherited document helpers. A
claim-quality upgrade must not replace that object wholesale. This mux sends
only claim research/drafting to the finalized litigation service; everything
else stays on the existing stable service.
"""

from __future__ import annotations

from typing import Any, Callable

from korgan.finalized_litigation import FinalizedProductionClaimService


class ClaimServiceMux:
    """Delegate claim methods to finalized litigation and all other API to stable."""

    def __init__(
        self,
        stable: Any,
        settings: Any,
        *,
        claim_factory: Callable[[Any], Any] = FinalizedProductionClaimService,
    ) -> None:
        self.stable = stable
        self.settings = stable.settings
        self._settings = settings
        self._claim_factory = claim_factory
        self._claim: Any | None = None

    def __getattr__(self, name: str) -> Any:
        return getattr(self.stable, name)

    def _claim_service(self) -> Any:
        if self._claim is None:
            self._claim = self._claim_factory(self._settings)
        return self._claim

    async def research_case(self, case_context: str, language: str = "ru"):
        return await self._claim_service().research_case(case_context, language=language)

    async def draft_claim(self, case_context: str, research: Any, language: str = "ru"):
        return await self._claim_service().draft_claim(case_context, research, language=language)
