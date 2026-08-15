from __future__ import annotations

from korgan_legal_ai.domain.models import LockedCase, RoutingDecision
from korgan_legal_ai.llm.base import LLMProvider
from korgan_legal_ai.prompts.router import ROUTER_SYSTEM


class TaskRouter:
    def __init__(self, provider: LLMProvider, model: str) -> None:
        self.provider = provider
        self.model = model

    def route(self, case: LockedCase) -> RoutingDecision:
        return self.provider.parse(
            model=self.model,
            system=ROUTER_SYSTEM,
            user=case.model_dump_json(indent=2),
            schema=RoutingDecision,
        )
