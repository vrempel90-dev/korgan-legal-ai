from datetime import date
from decimal import Decimal

from korgan_legal_ai.domain.models import Fact, Financials, LockedCase, Party, PartyRole, ProcedureFacts
from korgan_legal_ai.fact_lock.grounding import validate_locked_case_grounding


def _case(**kwargs) -> LockedCase:
    payload = {
        "raw_text": "unused",
        "parties": [
            Party(name="ТОО Альфа", role=PartyRole.CREDITOR),
            Party(name="ТОО Бета", role=PartyRole.DEBTOR),
        ],
        "facts": [Fact(statement="Есть задолженность")],
    }
    payload.update(kwargs)
    return LockedCase(**payload)


def test_grounding_accepts_values_actually_present_in_source() -> None:
    raw = (
        "ТОО «Альфа» поставило товар ТОО «Бета» на 8 450 000 тенге. "
        "Ответчик оплатил 3 000 000 тенге. Остаток долга — 5 450 000 тенге. "
        "Срок оплаты 5 марта 2026 года. Неустойка 0,1% в день, максимум 10%."
    )
    case = _case(
        facts=[Fact(statement="Срок оплаты 5 марта 2026 года", event_date=date(2026, 3, 5))],
        financials=Financials(
            contract_amount=Decimal("8450000"),
            payments=[Decimal("3000000")],
            principal=Decimal("5450000"),
            penalty_rate_percent_per_day=Decimal("0.1"),
            penalty_cap_percent_of_principal=Decimal("10"),
        ),
        procedure=ProcedureFacts(obligation_due_date=date(2026, 3, 5)),
    )

    assert validate_locked_case_grounding(raw, case) == []


def test_grounding_rejects_model_invented_amount_absent_from_source() -> None:
    raw = "ТОО Альфа требует взыскать с ТОО Бета 5 450 000 тенге."
    case = _case(financials=Financials(principal=Decimal("9999999")))

    issues = validate_locked_case_grounding(raw, case)

    assert any("principal" in issue for issue in issues)


def test_grounding_rejects_invented_party_and_date() -> None:
    raw = "ТОО Альфа заключило договор с ТОО Бета 10 февраля 2026 года."
    case = LockedCase(
        raw_text="unused",
        parties=[
            Party(name="ТОО Альфа", role=PartyRole.CREDITOR),
            Party(name="ТОО Гамма", role=PartyRole.DEBTOR),
        ],
        facts=[Fact(statement="Договор заключен", event_date=date(2026, 3, 10))],
    )

    issues = validate_locked_case_grounding(raw, case)

    assert any("наименование стороны" in issue for issue in issues)
    assert any("дату факта" in issue for issue in issues)


def test_grounding_accepts_spaced_identifier_exactly_from_source() -> None:
    raw = "Истец: ТОО Альфа, БИН 12 3456 7890 12. Ответчик: ТОО Бета."
    case = _case(
        parties=[
            Party(name="ТОО Альфа", role=PartyRole.CREDITOR, iin_bin="123456789012"),
            Party(name="ТОО Бета", role=PartyRole.DEBTOR),
        ]
    )

    assert validate_locked_case_grounding(raw, case) == []
