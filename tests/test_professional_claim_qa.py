from datetime import date
from decimal import Decimal

from korgan_legal_ai.domain.models import (
    CalculationResult,
    DocumentType,
    DraftDocument,
    Fact,
    Financials,
    LockedCase,
    Party,
    PartyRole,
    ProcedureFacts,
    ReadinessStatus,
)
from korgan_legal_ai.qa.service import FinalLegalQA


def _case() -> LockedCase:
    return LockedCase(
        raw_text="test",
        parties=[
            Party(name="ТОО Истец", role=PartyRole.CLAIMANT),
            Party(name="ТОО Ответчик", role=PartyRole.DEFENDANT),
        ],
        facts=[Fact(statement="Долг не оплачен")],
        financials=Financials(principal=Decimal("1000000")),
        procedure=ProcedureFacts(obligation_due_date=date(2026, 1, 15)),
    )


def _calculation() -> CalculationResult:
    return CalculationResult(
        principal=Decimal("1000000"),
        penalty=Decimal("0"),
        interest=Decimal("0"),
        other=Decimal("0"),
        total=Decimal("1000000"),
        currency="KZT",
    )


def test_qa_blocks_amount_changed_by_drafter() -> None:
    document = DraftDocument(
        document_type=DocumentType.CLAIM,
        text=(
            "Истец: ТОО Истец\nОтветчик: ТОО Ответчик\n"
            "Итого: 1000000 KZT\nПРОШУ СУД:\n"
            "1. Взыскать с ТОО Ответчик в пользу ТОО Истец задолженность в размере 1100000 KZT."
        ),
        readiness=ReadinessStatus.LAWYER_REVIEW_DRAFT,
        summary="x",
    )
    result = FinalLegalQA().check(_case(), document, [], calculation=_calculation())
    assert result.passed is False
    assert any(v.code == "AMOUNT_MISMATCH" for v in result.violations)


def test_qa_blocks_date_not_locked_or_derived() -> None:
    document = DraftDocument(
        document_type=DocumentType.CLAIM,
        text=(
            "Истец: ТОО Истец\nОтветчик: ТОО Ответчик\n"
            "Срок исполнения обязательства: 15.01.2026\n"
            "Дополнительное событие якобы произошло 17.02.2026.\n"
            "Итого: 1000000 KZT\nПРОШУ СУД:\n"
            "1. Взыскать с ТОО Ответчик в пользу ТОО Истец задолженность в размере 1000000 KZT."
        ),
        readiness=ReadinessStatus.LAWYER_REVIEW_DRAFT,
        summary="x",
    )
    result = FinalLegalQA().check(_case(), document, [], calculation=_calculation())
    assert result.passed is False
    assert any(v.code == "DATE_MISMATCH" for v in result.violations)
