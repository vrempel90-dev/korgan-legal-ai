from typing import TypeVar

from pydantic import BaseModel

from korgan_legal_ai.domain.exceptions import ClarificationRequired
from korgan_legal_ai.domain.models import Fact, Party, PartyRole
from korgan_legal_ai.fact_lock.service import FactLockExtraction, FactLockService
from korgan_legal_ai.llm.base import LLMProvider

T = TypeVar("T", bound=BaseModel)


class FakeProvider(LLMProvider):
    def __init__(self, value: BaseModel):
        self.value = value

    def parse(self, *, model: str, system: str, user: str, schema: type[T]) -> T:
        return schema.model_validate(self.value.model_dump())


def test_roles_are_locked_from_structured_extraction():
    extraction = FactLockExtraction(
        parties=[
            Party(name="A", role=PartyRole.CREDITOR),
            Party(name="B", role=PartyRole.DEBTOR),
        ],
        facts=[Fact(statement="B получил деньги от A")],
    )
    case = FactLockService(FakeProvider(extraction), "test").lock("raw")
    assert case.parties[0].role == PartyRole.CREDITOR
    assert case.parties[1].role == PartyRole.DEBTOR
    assert all(f.locked for f in case.facts)


def test_ambiguity_stops_pipeline():
    extraction = FactLockExtraction(
        parties=[Party(name="A", role=PartyRole.OTHER), Party(name="B", role=PartyRole.OTHER)],
        facts=[Fact(statement="Есть спор")],
        ambiguities=["Кто является кредитором?"],
    )
    service = FactLockService(FakeProvider(extraction), "test")
    try:
        service.lock("raw")
    except ClarificationRequired as exc:
        assert exc.questions == ["Кто является кредитором?"]
    else:
        raise AssertionError("ClarificationRequired expected")
