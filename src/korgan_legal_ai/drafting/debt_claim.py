from __future__ import annotations

from korgan_legal_ai.blueprints.registry import CLAIM_DEBT_RECOVERY
from korgan_legal_ai.drafting.generic import DocumentDrafter, DraftText
from korgan_legal_ai.llm.base import LLMProvider

__all__ = ["DebtClaimDrafter", "DraftText"]


class DebtClaimDrafter(DocumentDrafter):
    """Debt-recovery claim drafter.

    Kept as a named entry point because it is the workflow with the longest history and the most
    regression coverage. All behaviour now comes from the shared blueprint-driven drafter.
    """

    def __init__(self, provider: LLMProvider | None = None, model: str | None = None) -> None:
        super().__init__(CLAIM_DEBT_RECOVERY, provider=provider, model=model)
