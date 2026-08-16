from __future__ import annotations

from korgan.legal_types import ClaimDraft, LegalResearch
from korgan.senior_litigation_service import SeniorLitigationProductionService


class LitigationProductionService(SeniorLitigationProductionService):
    """Final production adapter for the litigation core.

    Senior research uses explicit PROCEDURE / REMEDY_DECISION /
    SENIOR_CORRECTION prefixes. The existing professional drafter already reads
    CASE_THEORY / REMEDY / RISK notes, so bridge those semantic channels before
    drafting. This is generic plumbing: no case name, document name or article
    number is encoded here.
    """

    @staticmethod
    def _bridge_senior_strategy(research: LegalResearch) -> None:
        additions: list[str] = []
        for note in list(research.notes):
            text = str(note)
            if text.startswith("PROCEDURE:"):
                additions.append("CASE_THEORY: SENIOR PROCEDURE — " + text.split(":", 1)[1].strip())
            elif text.startswith("REMEDY_DECISION:"):
                additions.append("REMEDY: SENIOR DECISION — " + text.split(":", 1)[1].strip())
            elif text.startswith("SENIOR_CORRECTION:"):
                additions.append("RISK: SENIOR CORRECTION — " + text.split(":", 1)[1].strip())
        research.notes = list(dict.fromkeys([*research.notes, *additions]))

    async def draft_claim(
        self,
        case_context: str,
        research: LegalResearch,
        language: str = "ru",
    ) -> ClaimDraft:
        self._bridge_senior_strategy(research)
        return await super().draft_claim(case_context, research, language=language)
