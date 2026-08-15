from datetime import date
from decimal import Decimal
import re

from korgan_legal_ai.domain.models import (
    DocumentType,
    Evidence,
    Fact,
    Financials,
    LegalArea,
    LockedCase,
    Party,
    PartyRole,
    ProcedureFacts,
    RoutingDecision,
)
from korgan_legal_ai.drafting.debt_claim import DebtClaimDrafter
from korgan_legal_ai.house_style import review_claim_presentation
from korgan_legal_ai.orchestration.debt_claim import DebtClaimWorkflow
from korgan_legal_ai.procedural.checker import ProceduralChecker
from korgan_legal_ai.research.gateway import CitationGateway


def _routing() -> RoutingDecision:
    return RoutingDecision(
        document_type=DocumentType.CLAIM,
        legal_area=LegalArea.DEBT_RECOVERY,
        confidence=1,
        rationale="synthetic regression",
    )


def _run(case: LockedCase, as_of: date):
    workflow = DebtClaimWorkflow(
        procedural=ProceduralChecker(CitationGateway()),
        drafter=DebtClaimDrafter(),
        as_of_date_provider=lambda: as_of,
    )
    result = workflow.run(case, _routing())
    assert result.qa.passed is True
    assert "NEEDS_VERIFICATION" in result.document.text
    # With an empty verified corpus/gateway in this test, no article number may be invented.
    assert not re.search(r"\b(?:ст\.|статья)\s*\d+", result.document.text, re.IGNORECASE)
    findings = {
        item.rule_id: item
        for item in review_claim_presentation(result.document, result.calculation)
    }
    assert findings["header.court_then_parties_then_price"].satisfied is True
    assert findings["calc.explicit_formula"].satisfied is True
    assert findings["closing.rukovodstvuyas_proshu_sud"].satisfied is True
    assert findings["calc.no_empty_catch_all_row"].satisfied is True
    assert "Иные суммы" not in result.document.text
    return result


def test_supply_partial_payment_penalty_cap_end_to_end():
    contract = Fact(statement="Поставка товара на 8 450 000 тенге")
    payment = Fact(statement="Ответчик оплатил 3 000 000 тенге")
    debt = Fact(statement="Остаток задолженности составляет 5 450 000 тенге")
    penalty = Fact(statement="Неустойка 0,1% в день, но не более 10% от суммы задолженности")
    case = LockedCase(
        raw_text="synthetic supply case",
        parties=[
            Party(name="ТОО Alpha Supply", role=PartyRole.CREDITOR),
            Party(name="ТОО Beta Market", role=PartyRole.DEBTOR),
        ],
        facts=[contract, payment, debt, penalty],
        evidence=[
            Evidence(title="Договор поставки", supports_fact_ids=[contract.id]),
            Evidence(title="Банковская выписка", supports_fact_ids=[payment.id]),
        ],
        financials=Financials(
            contract_amount=Decimal("8450000"),
            payments=[Decimal("3000000")],
            principal=Decimal("5450000"),
            penalty_rate_percent_per_day=Decimal("0.1"),
            penalty_cap_percent_of_principal=Decimal("10"),
        ),
        procedure=ProcedureFacts(obligation_due_date=date(2026, 3, 5)),
    )

    result = _run(case, date(2026, 8, 15))

    assert result.calculation.principal == Decimal("5450000")
    assert result.calculation.penalty_cap_amount == Decimal("545000.00")
    assert result.calculation.penalty == Decimal("545000.00")
    assert result.calculation.total == Decimal("5995000.00")
    assert result.calculation.principal_conflicts_with_payments is False
    assert "Итого: 5995000.00 KZT" in result.document.text


def test_carriage_partial_payment_explicit_penalty_end_to_end():
    service = Fact(statement="Услуги перевозки оказаны на 3 600 000 тенге")
    payment = Fact(statement="Оплачено 1 200 000 тенге")
    case = LockedCase(
        raw_text="synthetic carriage case",
        parties=[
            Party(name="ТОО Arman Logistics", role=PartyRole.CREDITOR),
            Party(name="ТОО Nova Trade", role=PartyRole.DEBTOR),
        ],
        facts=[service, payment],
        evidence=[Evidence(title="Акт оказанных услуг", supports_fact_ids=[service.id])],
        financials=Financials(
            contract_amount=Decimal("3600000"),
            payments=[Decimal("1200000")],
            principal=Decimal("2400000"),
            penalty=Decimal("158400"),
        ),
        procedure=ProcedureFacts(obligation_due_date=date(2026, 6, 3)),
    )

    result = _run(case, date(2026, 8, 15))

    assert result.calculation.principal == Decimal("2400000")
    assert result.calculation.penalty == Decimal("158400")
    assert result.calculation.total == Decimal("2558400")
    assert "Стоимость по договору: 3600000 KZT" in result.document.text
    assert "Оплачено: 1200000 KZT" in result.document.text
    assert "Итого: 2558400 KZT" in result.document.text


def test_contractor_partial_payment_end_to_end():
    work = Fact(statement="Подрядчик выполнил работы стоимостью 12 000 000 тенге")
    accepted = Fact(statement="Работы приняты заказчиком по акту")
    payment = Fact(statement="Заказчик оплатил 7 500 000 тенге")
    case = LockedCase(
        raw_text="synthetic contractor case",
        parties=[
            Party(name="ТОО Build Expert", role=PartyRole.CREDITOR),
            Party(name="ТОО City Project", role=PartyRole.DEBTOR),
        ],
        facts=[work, accepted, payment],
        evidence=[
            Evidence(title="Договор подряда", supports_fact_ids=[work.id]),
            Evidence(title="Акт выполненных работ", supports_fact_ids=[accepted.id]),
        ],
        financials=Financials(
            contract_amount=Decimal("12000000"),
            payments=[Decimal("7500000")],
            principal=Decimal("4500000"),
        ),
        procedure=ProcedureFacts(obligation_due_date=date(2026, 7, 1)),
    )

    result = _run(case, date(2026, 8, 15))

    assert result.calculation.principal == Decimal("4500000")
    assert result.calculation.penalty == Decimal("0")
    assert result.calculation.total == Decimal("4500000")
    assert result.calculation.principal_conflicts_with_payments is False
    assert "Итого: 4500000 KZT" in result.document.text
