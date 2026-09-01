"""Происхождение юридического утверждения остаётся явным до выпуска.

MISSING_FACT — отсутствие значения, а не приглашение модели заполнить пробел.
Классификация нужна только внутреннему конвейеру: ярлыки происхождения не могут
попасть в текст документа. Запрещённые реквизиты и доказательственные факты
проверяются против входящих материалов до DOCX.
"""

from __future__ import annotations

import pytest

from korgan.document_quality import assess_document_quality
from korgan.legal_provenance import (
    FactOrigin,
    ProvenancedFact,
    forbidden_fact_findings,
    render_fact,
)
from korgan.legal_types import ClaimDraft, LegalResearch, VerificationStatus
from korgan.pretrial import PretrialDraft
from korgan.pretrial_response import PretrialResponseDraft
from korgan.response_types import ResponseToClaimDraft


ALL_ORIGINS = {
    "FACT_FROM_USER",
    "FACT_FROM_DOCUMENT",
    "DERIVED_CALCULATION",
    "VERIFIED_LAW",
    "LEGAL_ANALYSIS",
    "MISSING_FACT",
}


MATERIALS = (
    "Истец: Ахметов Руслан Маратович, ИИН 900101300123, "
    "адрес: г. Алматы, ул. Абая, 150.\n"
    "Ответчик: ТОО «Компания», БИН 210987654321.\n"
    "Договор поставки № 12 от 15.01.2026 на сумму 2 300 000 тенге.\n"
    "Товар передан по накладной № 7 от 20.02.2026.\n"
    "Оплата 900 000 тенге подтверждается платёжным поручением № 45 от 01.03.2026.\n"
    "Претензия № 8 направлена 05.03.2026, почтовая квитанция приложена."
)


def test_fact_origin_contains_every_specified_class() -> None:
    assert {item.value for item in FactOrigin} == ALL_ORIGINS


def test_missing_fact_never_becomes_a_value() -> None:
    fact = ProvenancedFact(
        value="",
        origin=FactOrigin.MISSING_FACT,
        source="в материалах нет адреса ответчика",
    )

    assert render_fact(fact) == ""
    assert render_fact(fact, missing_marker="[ТРЕБУЕТ УТОЧНЕНИЯ: адрес ответчика]") == (
        "[ТРЕБУЕТ УТОЧНЕНИЯ: адрес ответчика]"
    )
    assert fact.usable is False


def test_missing_fact_cannot_be_relabelled_with_a_concrete_value() -> None:
    with pytest.raises(ValueError):
        ProvenancedFact(
            value="г. Астана, ул. Сыганак, 10",
            origin=FactOrigin.MISSING_FACT,
            source="",
        )


def test_internal_origin_labels_never_render_into_document_text() -> None:
    fact = ProvenancedFact(
        value="Договор № 12 заключён 15.01.2026.",
        origin=FactOrigin.FACT_FROM_DOCUMENT,
        source="contract.pdf",
    )

    rendered = render_fact(fact)

    assert rendered == "Договор № 12 заключён 15.01.2026."
    assert "FACT_FROM_DOCUMENT" not in rendered
    assert "FactOrigin" not in rendered


@pytest.mark.parametrize(
    ("statement", "expected_kind"),
    [
        ("Истец: Петров Пётр Иванович.", "ФИО"),
        ("Ответчик, БИН 999999999999.", "ИИН/БИН"),
        ("Адрес ответчика: г. Астана, ул. Сыганак, 10.", "адрес"),
        ("Между сторонами заключён договор № 99.", "номер договора"),
        ("Договор заключён 16.01.2026.", "дата"),
        ("Задолженность составляет 3 100 000 тенге.", "сумма"),
        ("Исполнение подтверждается актом выполненных работ № 88.", "доказательство"),
        ("Ответчик произвёл оплату 1 100 000 тенге.", "факт оплаты"),
        ("Претензия направлена ответчику 06.03.2026.", "факт направления претензии"),
    ],
)
def test_forbidden_invented_entity_is_detected(statement: str, expected_kind: str) -> None:
    findings = forbidden_fact_findings([statement], MATERIALS)

    assert findings
    assert any(expected_kind.lower() in item.lower() for item in findings), findings


def test_entities_present_in_materials_are_not_reported_as_invented() -> None:
    statements = [
        "Истец Ахметов Руслан Маратович, ИИН 900101300123, проживает по адресу: г. Алматы, ул. Абая, 150.",
        "Договор поставки № 12 заключён 15.01.2026 на сумму 2 300 000 тенге.",
        "Товар передан по накладной № 7 от 20.02.2026.",
        "Оплата 900 000 тенге произведена платёжным поручением № 45 от 01.03.2026.",
        "Претензия № 8 направлена 05.03.2026, что подтверждается почтовой квитанцией.",
    ]

    assert forbidden_fact_findings(statements, MATERIALS) == []


def test_derived_calculation_may_render_without_literal_presence_in_materials() -> None:
    fact = ProvenancedFact(
        value="Остаток основного долга: 1 400 000 тенге.",
        origin=FactOrigin.DERIVED_CALCULATION,
        source="2 300 000 − 900 000",
    )

    assert render_fact(fact) == "Остаток основного долга: 1 400 000 тенге."


def _research() -> LegalResearch:
    return LegalResearch(
        status=VerificationStatus.NEEDS_VERIFICATION,
        applicable_law=[],
        procedural_requirements=[],
        verified_claims=[],
        unverified_claims=[],
        source_urls=[],
        notes=[],
    )


def _claim_with(fact: str) -> ClaimDraft:
    return ClaimDraft(
        status=VerificationStatus.NEEDS_VERIFICATION,
        title="ИСКОВОЕ ЗАЯВЛЕНИЕ",
        court="Медеуский районный суд города Алматы",
        claimant=["Ахметов Руслан Маратович, ИИН 900101300123"],
        defendant=["ТОО «Компания», БИН 210987654321"],
        price_of_claim="2 300 000 тенге",
        facts=[fact],
        legal_basis=[fact],
        requests=[f"Взыскать основной долг 2 300 000 тенге. {fact}"],
        attachments=[fact],
        verification_notes=[fact],
        source_urls=[],
        state_duty="23 000 тенге",
    )


_UNSOURCED_FACT = "Товар передан по накладной № 99 от 03.03.2026."


def test_fact_absent_from_complete_materials_is_blocked() -> None:
    """Материалы полны по построению: чего в них нет, того нет в деле."""
    report = assess_document_quality("claim", MATERIALS, _research(), _claim_with(_UNSOURCED_FACT))

    assert any("накладн" in item.lower() for item in report.hard_blockers), report.hard_blockers


def test_same_fact_passes_when_the_materials_actually_contain_it() -> None:
    """Тот же факт допустим, если источник действительно его содержит."""
    materials = MATERIALS + "\nТовар передан по накладной № 99 от 03.03.2026."

    report = assess_document_quality("claim", materials, _research(), _claim_with(_UNSOURCED_FACT))

    assert not any("накладн" in item.lower() for item in report.hard_blockers), report.hard_blockers


def test_model_authored_sections_never_become_the_source_for_each_other() -> None:
    """Повтор факта в других разделах черновика не делает его подтверждённым.

    Правовое основание, просительная часть, приложения и примечания пишет та же
    модель. Если бы они засчитывались как источник, документ подтверждал бы сам
    себя, и детектор выдуманных реквизитов терял бы смысл.
    """
    draft = _claim_with(_UNSOURCED_FACT)
    assert _UNSOURCED_FACT in draft.legal_basis
    assert _UNSOURCED_FACT in draft.attachments

    report = assess_document_quality("claim", MATERIALS, _research(), draft)

    assert any("накладн" in item.lower() for item in report.hard_blockers), report.hard_blockers


def test_claim_gate_blocks_an_invented_payment_fact() -> None:
    draft = ClaimDraft(
        status=VerificationStatus.NEEDS_VERIFICATION,
        title="ИСКОВОЕ ЗАЯВЛЕНИЕ",
        court="Медеуский районный суд города Алматы",
        claimant=["Ахметов Руслан Маратович, ИИН 900101300123"],
        defendant=["ТОО «Компания», БИН 210987654321"],
        price_of_claim="2 300 000 тенге",
        facts=[
            "Договор поставки № 12 заключён 15.01.2026.",
            "Ответчик произвёл частичную оплату 1 100 000 тенге.",
            "Остаток долга не погашен.",
        ],
        legal_basis=[],
        requests=["Взыскать основной долг 2 300 000 тенге."],
        attachments=["Копия договора поставки № 12"],
        verification_notes=[],
        source_urls=[],
        state_duty="23 000 тенге",
    )

    report = assess_document_quality("claim", MATERIALS, _research(), draft)

    assert any("факт оплаты" in item.lower() for item in report.hard_blockers), report.hard_blockers


def test_response_gate_blocks_an_invented_evidence_reference() -> None:
    draft = ResponseToClaimDraft(
        status=VerificationStatus.NEEDS_VERIFICATION,
        title="ОТЗЫВ НА ИСКОВОЕ ЗАЯВЛЕНИЕ",
        court="Медеуский районный суд города Алматы",
        case_number="2-1234/2026",
        claimant=["Ахметов Руслан Маратович, ИИН 900101300123"],
        defendant=["ТОО «Компания», БИН 210987654321"],
        claim_summary=["Истец просит взыскать 2 300 000 тенге."],
        disputed_circumstances=["Исполнение опровергается актом выполненных работ № 88."],
        position=["Иск не признаётся."],
        objections=["Исполнение опровергается актом выполненных работ № 88."],
        calculation_review=["Сумма 2 300 000 тенге оспаривается полностью."],
        legal_basis=[],
        requests=["Отказать в удовлетворении иска."],
        attachments=[],
        verification_notes=[],
        source_urls=[],
    )

    report = assess_document_quality("response_to_claim", MATERIALS, _research(), draft)

    assert any("доказательство" in item.lower() for item in report.hard_blockers), report.hard_blockers


def test_pretrial_gate_blocks_an_invented_dispatch_date() -> None:
    draft = PretrialDraft(
        status=VerificationStatus.NEEDS_VERIFICATION,
        title="ДОСУДЕБНАЯ ПРЕТЕНЗИЯ",
        sender=["Ахметов Руслан Маратович, ИИН 900101300123"],
        recipient=["ТОО «Компания», БИН 210987654321"],
        facts=["Претензия ранее направлена ответчику 06.03.2026."],
        legal_basis=[],
        demands=["Оплатить 2 300 000 тенге."],
        deadline="",
        consequences=[],
        attachments=[],
        verification_notes=[],
        source_urls=[],
        calculation=["Основной долг: 2 300 000 тенге."],
    )

    report = assess_document_quality("pretrial", MATERIALS, _research(), draft)

    assert any("направления претензии" in item.lower() for item in report.hard_blockers), report.hard_blockers


def test_pretrial_response_gate_blocks_an_invented_contract_date() -> None:
    draft = PretrialResponseDraft(
        status=VerificationStatus.NEEDS_VERIFICATION,
        title="ОТВЕТ НА ДОСУДЕБНУЮ ПРЕТЕНЗИЮ",
        sender=["ТОО «Компания», БИН 210987654321"],
        recipient=["Ахметов Руслан Маратович, ИИН 900101300123"],
        reference="претензия № 8 от 05.03.2026",
        claim_summary=["Заявитель требует 2 300 000 тенге."],
        disputed_circumstances=["Договор поставки заключён 16.01.2026."],
        position=["Требование не признаётся."],
        objections=["Дата договора в претензии указана неверно."],
        calculation_review=["Сумма 2 300 000 тенге оспаривается."],
        legal_basis=[],
        response_terms=["Оплата не производится."],
        attachments=[],
        verification_notes=[],
        source_urls=[],
    )

    report = assess_document_quality("pretrial_response", MATERIALS, _research(), draft)

    assert any("дата" in item.lower() and "материал" in item.lower() for item in report.hard_blockers), report.hard_blockers
