"""Судебные издержки взыскиваются только те, что подтверждены материалами дела.

Иск просил взыскать 500 000 тенге расходов на оплату услуг представителя. В
деле не было ни договора об оказании юридических услуг, ни квитанции, ни
платёжного поручения, ни единого факта о том, что представитель вообще
привлекался. Релизный шлюз выпускал такой иск с оценкой 10.0.

Издержки — не правовое требование, а расход: он либо понесён и подтверждён
документом, либо его нет. Документ, который просит взыскать неподтверждённый
расход, обещает клиенту деньги, которых суд не присудит, и ослабляет
остальные требования.

Подтверждением считается названный в материалах документ об услуге или об её
оплате. Само требование подтверждением не является: «взыскать расходы на
представителя в размере 500 000 тенге» — это то, что проверяется.
"""

from __future__ import annotations

from korgan.document_quality import assess_document_quality
from korgan.expense_support import unsupported_expense_claims
from korgan.legal_types import ClaimDraft, LegalResearch, VerificationStatus
from korgan.provision_check import verified_claim_line

ADILET = "https://adilet.zan.kz/rus/docs/K940001000_"
ARTICLE_272 = (
    "Обязательство должно исполняться надлежащим образом в соответствии с условиями "
    "обязательства и требованиями законодательства, а при отсутствии таких условий и "
    "требований — в соответствии с обычаями делового оборота."
)

CONTEXT = (
    "Истец: ТОО «АЛЬЯНС», БИН 180340012345, г. Астана.\n"
    "Ответчик: ТОО «СТРОЙ ГРУПП», БИН 200140012345.\n"
    "12.01.2026 заключён договор поставки. Истец поставил оборудование, ответчик его не оплатил."
)

FACTS = [
    "12.01.2026 между сторонами заключён договор поставки оборудования.",
    "Истец поставил оборудование по накладной от 15.01.2026 на 1 200 000 тенге.",
    "Ответчик оборудование принял, но оплату в согласованный срок не произвёл.",
]

DEBT_REQUEST = "Взыскать с ответчика основной долг в размере 1 200 000 тенге."
REPRESENTATIVE_REQUEST = (
    "Взыскать с ответчика расходы на оплату услуг представителя в размере 500 000 тенге."
)
EXPERT_REQUEST = "Взыскать с ответчика расходы на проведение экспертизы в размере 250 000 тенге."


# --- сама проверка ---


def test_representative_expenses_without_any_document_are_unsupported() -> None:
    findings = unsupported_expense_claims([*FACTS, DEBT_REQUEST, REPRESENTATIVE_REQUEST])

    assert findings
    assert any("представител" in finding.lower() for finding in findings)


def test_the_demand_itself_is_not_its_own_proof() -> None:
    """Сумма в требовании — это то, что проверяется, а не подтверждение."""
    assert unsupported_expense_claims(
        ["Расходы на оплату услуг представителя составили 500 000 тенге.", REPRESENTATIVE_REQUEST]
    )


def test_a_contract_for_legal_services_in_the_attachments_supports_them() -> None:
    lines = [
        *FACTS,
        REPRESENTATIVE_REQUEST,
        "Договор об оказании юридических услуг от 20.01.2026",
        "Квитанция об оплате юридических услуг от 20.01.2026 на 500 000 тенге",
    ]

    assert unsupported_expense_claims(lines) == []


def test_a_payment_document_named_in_the_facts_supports_them() -> None:
    lines = [
        *FACTS,
        "Истец оплатил услуги представителя платёжным поручением № 44 от 20.01.2026.",
        REPRESENTATIVE_REQUEST,
    ]

    assert unsupported_expense_claims(lines) == []


def test_expert_costs_need_their_own_document() -> None:
    lines = [
        *FACTS,
        "Договор об оказании юридических услуг от 20.01.2026",
        REPRESENTATIVE_REQUEST,
        EXPERT_REQUEST,
    ]

    findings = unsupported_expense_claims(lines)

    assert len(findings) == 1
    assert "экспертиз" in findings[0].lower()


def test_payment_proof_for_the_debt_does_not_support_the_representative() -> None:
    """Платёжное поручение по поставке ничего не говорит о юридических услугах."""
    lines = [
        *FACTS,
        "Оплата по договору поставки подтверждается платёжным поручением от 15.01.2026.",
        REPRESENTATIVE_REQUEST,
    ]

    assert unsupported_expense_claims(lines)


def test_a_claim_without_any_expense_demand_is_not_touched() -> None:
    assert unsupported_expense_claims([*FACTS, DEBT_REQUEST]) == []


def test_state_duty_is_not_an_expense_this_check_owns() -> None:
    """Пошлина считается детерминированно и живёт в claim_state_duty."""
    assert (
        unsupported_expense_claims(
            [*FACTS, DEBT_REQUEST, "Взыскать с ответчика государственную пошлину 36 000 тенге."]
        )
        == []
    )


# --- шлюз выпуска ---


def _claim(*, requests: list[str], attachments: list[str]) -> ClaimDraft:
    return ClaimDraft(
        status=VerificationStatus.VERIFIED,
        title="Исковое заявление о взыскании задолженности",
        court="Специализированный межрайонный экономический суд города Астаны",
        claimant=["ТОО «АЛЬЯНС», БИН 180340012345"],
        defendant=["ТОО «СТРОЙ ГРУПП», БИН 200140012345"],
        price_of_claim="1 200 000 тенге",
        state_duty="36 000 тенге",
        facts=list(FACTS),
        legal_basis=["Обязательство должно исполняться надлежащим образом (статья 272 ГК РК)."],
        requests=requests,
        attachments=attachments,
        verification_notes=[],
        source_urls=[ADILET],
    )


def _research() -> LegalResearch:
    return LegalResearch(
        status=VerificationStatus.VERIFIED,
        applicable_law=["статья 272 ГК РК"],
        procedural_requirements=[],
        verified_claims=[
            verified_claim_line(
                "Обязательство должно исполняться надлежащим образом",
                "статья 272 ГК РК",
                ARTICLE_272,
                ADILET,
            )
        ],
        unverified_claims=[],
        notes=["VERIFIED_COURT: Специализированный межрайонный экономический суд города Астаны"],
        source_urls=[ADILET],
    )


def test_quality_gate_blocks_unsupported_representative_expenses() -> None:
    draft = _claim(
        requests=[DEBT_REQUEST, REPRESENTATIVE_REQUEST],
        attachments=["Договор поставки от 12.01.2026", "Накладная от 15.01.2026"],
    )

    report = assess_document_quality("claim", CONTEXT, _research(), draft)

    assert report.ready is False
    assert any("представител" in blocker.lower() for blocker in report.hard_blockers)


def test_quality_gate_releases_them_once_the_documents_are_attached() -> None:
    draft = _claim(
        requests=[DEBT_REQUEST, REPRESENTATIVE_REQUEST],
        attachments=[
            "Договор поставки от 12.01.2026",
            "Накладная от 15.01.2026",
            "Договор об оказании юридических услуг от 20.01.2026",
            "Квитанция об оплате юридических услуг на 500 000 тенге",
        ],
    )

    report = assess_document_quality("claim", CONTEXT, _research(), draft)

    assert report.ready is True
    assert not any("представител" in blocker.lower() for blocker in report.hard_blockers)
