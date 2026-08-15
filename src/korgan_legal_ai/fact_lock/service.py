from __future__ import annotations

from pydantic import BaseModel, Field

from korgan_legal_ai.domain.exceptions import ClarificationRequired
from korgan_legal_ai.domain.models import Evidence, Fact, Financials, LockedCase, Party
from korgan_legal_ai.llm.base import LLMProvider
from korgan_legal_ai.prompts.fact_lock import FACT_LOCK_SYSTEM


class FactLockExtraction(BaseModel):
    parties: list[Party]
    facts: list[Fact]
    evidence: list[Evidence] = Field(default_factory=list)
    financials: Financials = Field(default_factory=Financials)
    ambiguities: list[str] = Field(default_factory=list)


class FactLockService:
    def __init__(self, provider: LLMProvider, model: str) -> None:
        self.provider = provider
        self.model = model

    def lock(self, raw_text: str) -> LockedCase:
        extracted = self.provider.parse(
            model=self.model,
            system=FACT_LOCK_SYSTEM,
            user=raw_text,
            schema=FactLockExtraction,
        )
        if extracted.ambiguities:
            raise ClarificationRequired(extracted.ambiguities)
        return LockedCase(raw_text=raw_text, **extracted.model_dump())
