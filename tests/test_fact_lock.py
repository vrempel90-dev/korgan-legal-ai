from datetime import date
from decimal import Decimal
from typing import TypeVar

from pydantic import BaseModel

from korgan_legal_ai.domain.exceptions import ClarificationRequired
from korgan_legal_ai.domain.models import Fact, Party, PartyRole
from korgan_legal_ai.fact_lock.service import (
    FactLockExtraction,
    FactLockService,
    FactLockWireExtraction,
)
from korgan_legal_ai.llm.base import LLMProvider

T = TypeVar("T", bound=BaseModel)


class FakeProvider(LLMProvider):
    def __init__(self, value: BaseModel):
        self.value = value

    def parse(self, *, model: str, system: str, user: str, schema: type[T]) -> T:
        return schema.model_validate(self.value.model_dump())


def _wire(**overrides) -> FactLockWireExtraction:
    payload = {
        "parties": [
            {"name": "A", "role": "creditor"},
            {"name": "B", "role": "debtor"},
        ],
        "facts": [{"id": "f1", "statement": "B получил деньги от A"}],
    }
    payload.update(overrides)
    return FactLockWireExtraction.model_validate(payload)


def test_roles_are_locked_from_structured_extraction():
    case = FactLockService(FakeProvider(_wire()), "test").lock("raw")
    assert case.parties[0].role == PartyRole.CREDITOR
    assert case.parties[1].role == PartyRole.DEBTOR
    assert all(f.locked for f in case.facts)


def test_contract_penalty_rate_and_cap_are_not_money_amounts():
    wire = _wire(
        facts=[
            {
                "id": "f1",
                "statement": "Неустойка 0,1% в день, но не более 10% от долга",
            }
        ],
        financials={
            "principal": "2400000",
            "penalty": None,
            "penalty_rate_percent_per_day": "0.1",
            "penalty_cap_percent_of_principal": "10",
        },
    )
    case = FactLockService(FakeProvider(wire), "test").lock("raw")

    assert case.financials.principal == Decimal("2400000")
    assert case.financials.penalty is None
    assert case.financials.penalty_rate_percent_per_day == Decimal("0.1")
    assert case.financials.penalty_cap_percent_of_principal == Decimal("10")


def test_domain_extraction_still_normalizes_unambiguous_russian_date_formats():
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
    wire = _wire(ambiguities=["Кто является кредитором?"])
    service = FactLockService(FakeProvider(wire), "test")
    try:
        service.lock("raw")
    except ClarificationRequired as exc:
        assert exc.questions == ["Кто является кредитором?"]
    else:
        raise AssertionError("ClarificationRequired expected")


def test_wire_schema_normalizes_russian_dates_and_spaced_tenge_without_sdk_types():
    wire = FactLockWireExtraction.model_validate(
        {
            "parties": [
                {"name": "ТОО Альфа Строй", "role": "creditor"},
                {"name": "ТОО Бета Сервис", "role": "debtor"},
            ],
            "facts": [
                {
                    "id": "f1",
                    "statement": "Договор заключен 10 февраля 2026 года",
                    "event_date": "10 февраля 2026 года",
                },
                {
                    "id": "f2",
                    "statement": "Срок оплаты — 5 марта 2026 года",
                    "event_date": "2026-03-05",
                },
            ],
            "financials": {
                "contract_amount": "8 450 000 тенге",
                "payments": ["3 000 000 тенге"],
                "principal": "5 450 000 тенге",
                "penalty_rate_percent_per_day": "0,1",
                "penalty_cap_percent_of_principal": "10",
                "currency": "KZT",
            },
            "procedure": {
                "obligation_due_date": "5 марта 2026 года",
                "pretrial_demand_sent_date": "15 апреля 2026 года",
            },
        }
    )

    case = FactLockService(FakeProvider(wire), "test").lock("raw")

    assert case.facts[0].event_date == date(2026, 2, 10)
    assert case.procedure.obligation_due_date == date(2026, 3, 5)
    assert case.procedure.pretrial_demand_sent_date == date(2026, 4, 15)
    assert case.financials.contract_amount == Decimal("8450000")
    assert case.financials.payments == [Decimal("3000000")]
    assert case.financials.principal == Decimal("5450000")
    assert case.financials.penalty_rate_percent_per_day == Decimal("0.1")
    assert case.financials.penalty_cap_percent_of_principal == Decimal("10")


def test_unparseable_wire_money_fails_closed_as_clarification():
    wire = _wire(financials={"principal": "примерно пять миллионов"})
    service = FactLockService(FakeProvider(wire), "test")
    try:
        service.lock("raw")
    except ClarificationRequired as exc:
        assert any("principal" in question for question in exc.questions)
    else:
        raise AssertionError("ClarificationRequired expected")


def test_invalid_wire_role_fails_closed_instead_of_becoming_a_party_fact():
    wire = _wire(
        parties=[
            {"name": "A", "role": "invented_role"},
            {"name": "B", "role": "debtor"},
        ]
    )
    try:
        FactLockService(FakeProvider(wire), "test").lock("raw")
    except ClarificationRequired as exc:
        assert any("роль стороны A" in question for question in exc.questions)
    else:
        raise AssertionError("ClarificationRequired expected")
