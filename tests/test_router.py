from typing import TypeVar

from pydantic import BaseModel

from korgan_legal_ai.domain.models import (
    DocumentType,
    Fact,
    LegalArea,
    LockedCase,
    Party,
    PartyRole,
    RoutingDecision,
)
from korgan_legal_ai.llm.base import LLMProvider
from korgan_legal_ai.router.service import TaskRouter

T = TypeVar("T", bound=BaseModel)


class FakeProvider(LLMProvider):
    def parse(self, *, model: str, system: str, user: str, schema: type[T]) -> T:
        return schema.model_validate(
            RoutingDecision(
                document_type=DocumentType.CLAIM,
                legal_area=LegalArea.DEBT_RECOVERY,
                confidence=0.99,
                rationale="Debt claim requested",
            ).model_dump()
        )


def test_router_returns_single_workflow():
    case = LockedCase(
        raw_text="Взыскать долг",
        parties=[Party(name="A", role=PartyRole.CREDITOR), Party(name="B", role=PartyRole.DEBTOR)],
        facts=[Fact(statement="Долг не возвращен")],
    )
    decision = TaskRouter(FakeProvider(), "test").route(case)
    assert decision.document_type == DocumentType.CLAIM
    assert decision.legal_area == LegalArea.DEBT_RECOVERY
