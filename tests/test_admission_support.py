"""Признание стороны не может быть создано самим проектом ответа.

``admitted_circumstances`` — процессуально чувствительный раздел. Фраза
«ответчик не оспаривает долг 1 400 000 тенге» может повлиять на исход дела и
не становится безопасной оттого, что модель записала её одновременно в
admitted_circumstances, position и settlement_offer. Источник признания должен
существовать во входящих материалах как прямое волеизъявление доверителя.

Нейтральный факт существования договора проверяется мягче: он должен дословно
следовать из материалов и не содержать признания исполнения, нарушения,
качества, долга или суммы. Пустой раздел по-прежнему является безопасным и
полноценным результатом.
"""

from __future__ import annotations

from korgan.admission_support import unsupported_admissions
from korgan.document_quality import assess_document_quality
from korgan.legal_types import LegalResearch, VerificationStatus
from korgan.pretrial_response import PretrialResponseDraft
from korgan.response_types import ResponseToClaimDraft

ADILET = "https://adilet.zan.kz/rus/docs/K940001000_"
COURT = "Специализированный межрайонный экономический суд города Астаны"
BASE_CONTEXT = (
    "Истец: ТОО «АЛЬЯНС», БИН 180340012345.\n"
    "Ответчик: ТОО «СТРОЙ ГРУПП», БИН 200140012345.\n"
    "Между сторонами заключён договор поставки № 12 от 15.01.2026.\n"
    "Истец утверждает, что ответчик должен 2 300 000 тенге.\n"
    "Ответчик о своей позиции по долгу в материалах не сообщал."
)
NEUTRAL_ADMISSION = "Факт заключения договора поставки № 12 от 15.01.2026 не оспаривается."
MONEY_ADMISSION = "Ответчик признаёт основной долг в размере 1 400 000 тенге."


def _research() -> LegalResearch:
    return LegalResearch(
        status=VerificationStatus.VERIFIED,
        applicable_law=[],
        procedural_requirements=[],
        verified_claims=[],
        unverified_claims=[],
        notes=[f"VERIFIED_COURT: {COURT}"],
        source_urls=[ADILET],
    )


def _response(*, admissions: list[str]) -> ResponseToClaimDraft:
    return ResponseToClaimDraft(
        status=VerificationStatus.VERIFIED,
        title="ОТЗЫВ НА ИСКОВОЕ ЗАЯВЛЕНИЕ",
        court=COURT,
        case_number="7199-26-00-2/1234",
        claimant=["ТОО «АЛЬЯНС», БИН 180340012345"],
        defendant=["ТОО «СТРОЙ ГРУПП», БИН 200140012345"],
        claim_summary=["Истец просит взыскать основной долг 2 300 000 тенге."],
        admitted_circumstances=admissions,
        disputed_circumstances=["Размер долга 2 300 000 тенге оспаривается."],
        position=["Иск не признаётся."],
        objections=["Истец не представил подписанную товарную накладную."],
        calculation_review=["Расчёт долга 2 300 000 тенге документально не подтверждён."],
        legal_basis=["Обязанность оплаты возникает из подтверждённого исполнения договора."],
        requests=["Отказать в удовлетворении иска."],
        attachments=["Копия договора поставки"],
        verification_notes=[],
        source_urls=[ADILET],
    )


def _pretrial_response(*, admissions: list[str]) -> PretrialResponseDraft:
    return PretrialResponseDraft(
        status=VerificationStatus.VERIFIED,
        title="ОТВЕТ НА ДОСУДЕБНУЮ ПРЕТЕНЗИЮ",
        sender=["ТОО «СТРОЙ ГРУПП», БИН 200140012345"],
        recipient=["ТОО «АЛЬЯНС», БИН 180340012345"],
        reference="претензия от 05.03.2026 № 7",
        claim_summary=["Заявитель требует уплатить основной долг 2 300 000 тенге."],
        admitted_circumstances=admissions,
        disputed_circumstances=["Размер долга 2 300 000 тенге оспаривается."],
        position=["Требование не признаётся."],
        objections=["Заявитель не представил подписанную товарную накладную."],
        calculation_review=["Расчёт долга 2 300 000 тенге документально не подтверждён."],
        legal_basis=["Обязанность оплаты возникает из подтверждённого исполнения договора."],
        response_terms=["Оснований для оплаты не имеется."],
        attachments=["Копия договора поставки"],
        verification_notes=[],
        source_urls=[ADILET],
    )


def test_opponents_allegation_is_not_the_clients_admission() -> None:
    findings = unsupported_admissions([MONEY_ADMISSION], BASE_CONTEXT)

    assert findings
    assert any("1 400 000" in finding for finding in findings)


def test_defendant_identity_heading_does_not_turn_later_prose_into_a_client_admission() -> None:
    context = (
        "Ответчик: ТОО «СТРОЙ ГРУПП», БИН 200140012345.\n"
        "Основной долг признаётся в размере 1 400 000 тенге."
    )

    assert unsupported_admissions([MONEY_ADMISSION], context)


def test_repeating_an_admission_elsewhere_in_the_draft_is_not_external_support() -> None:
    context = BASE_CONTEXT
    model_authored_materials = [
        MONEY_ADMISSION,
        "Требование признаётся в части 1 400 000 тенге.",
        "Готовы оплатить 1 400 000 тенге.",
    ]

    assert unsupported_admissions([MONEY_ADMISSION], context, model_authored_materials)


def test_explicit_client_admission_in_materials_supports_the_same_admission() -> None:
    context = BASE_CONTEXT + "\nПозиция ответчика: признаём основной долг в размере 1 400 000 тенге."

    assert unsupported_admissions([MONEY_ADMISSION], context) == []


def test_neutral_contract_fact_is_safe_when_the_materials_contain_it() -> None:
    assert unsupported_admissions([NEUTRAL_ADMISSION], BASE_CONTEXT) == []


def test_neutral_fact_with_an_invented_contract_number_is_blocked() -> None:
    invented = "Факт заключения договора поставки № 99 от 15.01.2026 не оспаривается."

    assert unsupported_admissions([invented], BASE_CONTEXT)


def test_empty_admissions_are_safe() -> None:
    assert unsupported_admissions([], BASE_CONTEXT) == []


def test_response_gate_blocks_an_unsupported_money_admission() -> None:
    report = assess_document_quality(
        "response_to_claim", BASE_CONTEXT, _research(), _response(admissions=[MONEY_ADMISSION])
    )

    assert report.ready is False
    assert any("признан" in blocker.lower() for blocker in report.hard_blockers), report.hard_blockers


def test_response_gate_allows_an_explicitly_sourced_money_admission() -> None:
    context = BASE_CONTEXT + "\nПозиция ответчика: признаём основной долг в размере 1 400 000 тенге."
    report = assess_document_quality(
        "response_to_claim", context, _research(), _response(admissions=[MONEY_ADMISSION])
    )

    assert not any("признан" in blocker.lower() for blocker in report.hard_blockers), report.hard_blockers


def test_pretrial_response_gate_blocks_an_unsupported_money_admission() -> None:
    report = assess_document_quality(
        "pretrial_response", BASE_CONTEXT, _research(), _pretrial_response(admissions=[MONEY_ADMISSION])
    )

    assert report.ready is False
    assert any("признан" in blocker.lower() for blocker in report.hard_blockers), report.hard_blockers


def test_pretrial_response_keeps_empty_admissions_safe() -> None:
    report = assess_document_quality(
        "pretrial_response", BASE_CONTEXT, _research(), _pretrial_response(admissions=[])
    )

    assert not any("признан" in blocker.lower() for blocker in report.hard_blockers), report.hard_blockers
