"""Scope the client's material-law completeness requirement to pre-trial demands.

The ordinary claim pipeline must keep the behaviour it had before the client
remark about the pre-trial demand: research and Word generation are not wrapped
in the additional material-law release gate.  Pre-trial demands still receive
the targeted second-pass search and material-law completeness check implemented
by :class:`AdditiveLegalGuardService`.
"""

from __future__ import annotations

from korgan.additive_legal_guard import AdditiveLegalGuardService
from korgan.legal_types import LegalResearch
from korgan.stable_legal_release import sanitize_research_sources


class PretrialOnlyMaterialGuardService(AdditiveLegalGuardService):
    """Use the enhanced material-law search only for pre-trial demands."""

    async def research_case(
        self,
        case_context: str,
        language: str = "ru",
    ) -> LegalResearch:
        """Claim research: bypass the additive material-law second pass."""
        research = await super(AdditiveLegalGuardService, self).research_case(
            case_context,
            language=language,
        )
        return sanitize_research_sources(research)

    async def research_pretrial(
        self,
        case_context: str,
        language: str = "ru",
    ) -> LegalResearch:
        """Pre-trial research: keep the client's enhanced material-law pass."""
        research = await AdditiveLegalGuardService.research_case(
            self,
            case_context,
            language=language,
        )
        return sanitize_research_sources(research)

    async def research_response_to_claim(
        self,
        case_context: str,
        language: str = "ru",
    ) -> LegalResearch:
        """Response research: keep inherited production behaviour, no new client rule."""
        research = await super(AdditiveLegalGuardService, self).research_response_to_claim(
            case_context,
            language=language,
        )
        return sanitize_research_sources(research)

    async def draft_response_to_claim(
        self,
        case_context: str,
        research: LegalResearch,
        language: str = "ru",
    ):
        """Do not apply the client-specific material-law response post-check."""
        return await super(AdditiveLegalGuardService, self).draft_response_to_claim(
            case_context,
            research,
            language=language,
        )

    async def research_contract(
        self,
        case_context: str,
        language: str = "ru",
    ) -> LegalResearch:
        """Contract research: keep inherited production behaviour, no new client rule."""
        research = await super(AdditiveLegalGuardService, self).research_contract(
            case_context,
            language=language,
        )
        return sanitize_research_sources(research)
