from datetime import date
from decimal import Decimal
from typing import TypeVar

from pydantic import BaseModel

from korgan_legal_ai.domain.exceptions import ClarificationRequired
from korgan_legal_ai.domain.models import Fact, Financials, Party, PartyRole
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


def test_contract_penalty_rate_and_cap_are_not_money_amounts():
    extraction = FactLockExtraction(
        parties=[
            Party(name="A", role=PartyRole.CREDITOR),
            Party(name="B", role=PartyRole.DEBTOR),
        ],
        facts=[Fact(statement="Неустойка 0,1% в день, но не более 10% от долга")],
        financials=Financials(
            principal=Decimal("2400000"),
            penalty=None,
            penalty_rate_percent_per_day=Decimal("0.1"),
            penalty_cap_percent_of_principal=Decimal("10"),
        ),
    )

    case = FactLockService(FakeProvider(extraction), "test").lock("raw")

    assert case.financials.principal == Decimal("2400000")
    assert case.financials.penalty is None
    assert case.financials.penalty_rate_percent_per_day == Decimal("0.1")
    assert case.financials.penalty_cap_percent_of_principal == Decimal("10")


def test_structured_fact_lock_normalizes_unambiguous_russian_date_formats():
    extraction = FactLockExtraction.model_validate(
        {
            "parties": [
                {"name": "A", "role": "creditor"},
                {"name": "B", "role": "debtor"},
            ],
            "facts": [
                {"statement": "Договор заключен", "event_date": "05.05.2026"},
                {"statement": "Акт подписан", "event_date": "28 мая 2026 года"},
                {"statement": "Оплата просрочена", "event_date": "2026-06-10T00:00:00"},
            ],
            "procedure": {
                "obligation_due_date": "10.06.2026",
                "pretrial_demand_sent_date": "1 августа 2026 года",
            },
        }
    )

    assert [fact.event_date for fact in extraction.facts] == [
        date(2026, 5, 5),
        date(2026, 5, 28),
        date(2026, 6, 10),
    ]
    assert extraction.procedure.obligation_due_date == date(2026, 6, 10)
    assert extraction.procedure.pretrial_demand_sent_date == date(2026, 8, 1)


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
