from typing import TypeVar

from pydantic import BaseModel

from korgan_legal_ai.domain.models import (
    DocumentType,
    LegalArea,
    RoutingDecision,
)
from korgan_legal_ai.drafting.debt_claim import DebtClaimDrafter
from korgan_legal_ai.fact_lock.service import FactLockService, FactLockWireExtraction
from korgan_legal_ai.llm.base import LLMProvider
from korgan_legal_ai.orchestration.debt_claim import DebtClaimWorkflow
from korgan_legal_ai.orchestration.engine import LegalEngine
from korgan_legal_ai.procedural.checker import ProceduralChecker
from korgan_legal_ai.research.gateway import CitationGateway
from korgan_legal_ai.router.service import TaskRouter

T = TypeVar("T", bound=BaseModel)


class SequencedProvider(LLMProvider):
    def __init__(self):
        self.calls = 0

    def parse(self, *, model: str, system: str, user: str, schema: type[T]) -> T:
        self.calls += 1
        if schema is FactLockWireExtraction:
            return schema.model_validate(
                {
                    "parties": [
                        {"name": "A", "role": "creditor"},
                        {"name": "B", "role": "debtor"},
                    ],
                    "facts": [{"id": "f1", "statement": "B не вернул долг A"}],
                    "financials": {"principal": "500"},
                }
            )
        if schema is RoutingDecision:
            return schema.model_validate(
                RoutingDecision(
                    document_type=DocumentType.CLAIM,
                    legal_area=LegalArea.DEBT_RECOVERY,
                    confidence=1,
                    rationale="debt",
                ).model_dump()
            )
        raise AssertionError(f"Unexpected schema: {schema}")


def test_engine_runs_fact_lock_router_and_workflow():
    provider = SequencedProvider()
    engine = LegalEngine(
        fact_lock=FactLockService(provider, "test"),
        router=TaskRouter(provider, "test"),
        debt_claim=DebtClaimWorkflow(
            procedural=ProceduralChecker(CitationGateway()),
            drafter=DebtClaimDrafter(),
        ),
    )
    result = engine.process("A дал B 500, B не вернул. Составь иск.")
    assert provider.calls == 2
    assert result.qa.passed is True
    assert result.routing.legal_area == LegalArea.DEBT_RECOVERY
