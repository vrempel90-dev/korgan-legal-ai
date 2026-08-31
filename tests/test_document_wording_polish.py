"""Профессиональный вид документа: формулировки шапки не должны быть корявыми.

Оба дефекта здесь видны клиенту сразу, в первых строках документа, и оба
рождаются одинаково: боевой рендерер приклеивает свой префикс к строке, в
которой этот префикс уже есть или которая стоит не в том падеже.

1. Ответ на претензию печатал «На претензия от 05.03.2026 № 7».
   ``_reference_line`` подставляла винительный падеж «На {value}» к
   именительному значению, пришедшему из анкеты/модели.

2. Отзыв на иск печатал «Гражданское дело № дело № 2-1234/2026».
   Пользователь пишет номер так, как он напечатан в определении суда —
   «дело № 2-1234/2026», — а рендерер добавлял собственное «Гражданское дело №».

Проверяются канонические production-рендереры (``build_pretrial_response_docx``
и ``build_response_to_claim_docx``) через тот же ``docx_text``, которым
измеряет качество боевой gate: правка обязана жить в конвейере, а не в
строковой замене поверх готового DOCX.
"""

from __future__ import annotations

import re

import pytest

from korgan.document_quality import docx_text
from korgan.legal_types import VerificationStatus
from korgan.pretrial_response import PretrialResponseDraft, build_pretrial_response_docx
from korgan.response_docx import build_response_to_claim_docx
from korgan.response_types import ResponseToClaimDraft

GK_GENERAL_URL = "https://adilet.zan.kz/rus/docs/K940001000_"
ARTICLE_272 = "Обязательство должно исполняться надлежащим образом в соответствии с условиями обязательства."


def _pretrial_response(**overrides) -> PretrialResponseDraft:
    data = dict(
        status=VerificationStatus.VERIFIED,
        title="ОТВЕТ НА ДОСУДЕБНУЮ ПРЕТЕНЗИЮ",
        sender=['ТОО «Компания», БИН 210987654321'],
        recipient=["Ахметов Руслан Маратович, ИИН 900101300123"],
        reference="претензия от 05.03.2026 № 7",
        claim_summary=["Заявлено требование об оплате 2 300 000 тенге."],
        admitted_circumstances=["Факт заключения договора № 12 от 15.01.2026 не оспаривается."],
        disputed_circumstances=["Оспаривается объём принятых работ по акту от 20.02.2026."],
        position=["Требование признаётся в части 1 400 000 тенге."],
        objections=["Работы на сумму 900 000 тенге не приняты: акт от 20.02.2026 подписан с замечаниями."],
        calculation_review=["Начисление произведено с 01.03.2026 при сроке оплаты 20.03.2026 по пункту 4.2 договора."],
        legal_basis=[f"{ARTICLE_272} Правовое основание: статья 272 ГК РК."],
        settlement_offer="",
        response_terms=["Признанная часть будет оплачена в согласованный сторонами срок."],
        attachments=["Копия акта от 20.02.2026"],
        verification_notes=[],
        source_urls=[GK_GENERAL_URL],
    )
    data.update(overrides)
    return PretrialResponseDraft(**data)


def _response(**overrides) -> ResponseToClaimDraft:
    data = dict(
        status=VerificationStatus.VERIFIED,
        title="ОТЗЫВ НА ИСКОВОЕ ЗАЯВЛЕНИЕ",
        court="Медеуский районный суд города Алматы",
        case_number="дело № 2-1234/2026",
        claimant=["Ахметов Руслан Маратович, ИИН 900101300123"],
        defendant=['ТОО «Компания», БИН 210987654321'],
        claim_summary=["Истец просит взыскать 2 300 000 тенге."],
        admitted_circumstances=["Факт заключения договора № 12 от 15.01.2026 не оспаривается."],
        disputed_circumstances=["Оспаривается объём принятых работ по акту от 20.02.2026."],
        position=["Иск подлежит частичному удовлетворению в размере 1 400 000 тенге."],
        objections=["Работы на сумму 900 000 тенге не приняты: акт от 20.02.2026 подписан с замечаниями."],
        calculation_review=["Начисление произведено с 01.03.2026 при сроке оплаты 20.03.2026 по пункту 4.2 договора."],
        legal_basis=[f"{ARTICLE_272} Правовое основание: статья 272 ГК РК."],
        requests=["Отказать в удовлетворении исковых требований в части 900 000 тенге."],
        attachments=["Копия акта от 20.02.2026"],
        verification_notes=[],
        source_urls=[GK_GENERAL_URL],
    )
    data.update(overrides)
    return ResponseToClaimDraft(**data)


# --- «На претензия» -------------------------------------------------------

# Именительный падеж после предлога «на» — то, что реально печаталось.
# Формы записи ссылки взяты из анкеты: клиент пишет их именно так.
NOMINATIVE_REFERENCES: tuple[str, ...] = (
    "претензия от 05.03.2026 № 7",
    "Претензия №1",
    "претензия № 7 от 05.03.2026",
    "досудебная претензия № 7",
    "Досудебная претензия от 05.03.2026 № 7",
)


@pytest.mark.parametrize("reference", NOMINATIVE_REFERENCES)
def test_response_to_pretrial_never_prints_nominative_after_na(reference: str) -> None:
    text = docx_text(build_pretrial_response_docx(_pretrial_response(reference=reference)))

    assert not re.search(r"\bНа\s+претензия\b", text, re.IGNORECASE), text[:400]
    assert not re.search(r"\bНа\s+досудебная\s+претензия\b", text, re.IGNORECASE), text[:400]


@pytest.mark.parametrize("reference", NOMINATIVE_REFERENCES)
def test_response_to_pretrial_keeps_the_reference_itself(reference: str) -> None:
    """Падеж чинится не удалением ссылки: номер и дата обязаны остаться."""
    text = docx_text(build_pretrial_response_docx(_pretrial_response(reference=reference)))

    for token in re.findall(r"[№\d][\d./-]*", reference):
        assert token in text, (token, text[:400])


def test_response_to_pretrial_keeps_correct_reference_untouched() -> None:
    """Сокращённая ссылка «исх. № …» падежа не требует и склоняться не должна.

    Форма закреплена в tests/test_pretrial_reference_style.py: правка падежа
    обязана быть узкой и не переписывать уже корректные шапки.
    """
    text = docx_text(build_pretrial_response_docx(_pretrial_response(reference="исх. № 42 от 15.07.2026")))

    assert "На исх. № 42 от 15.07.2026" in text


def test_response_to_pretrial_does_not_duplicate_existing_na_prefix() -> None:
    text = docx_text(build_pretrial_response_docx(_pretrial_response(reference="На претензию № 7 от 05.03.2026")))

    assert "На На" not in text
    assert text.count("На претензию № 7 от 05.03.2026") == 1


# --- «Гражданское дело № дело № …» ----------------------------------------

# Клиент переписывает номер из определения суда вместе со словом «дело».
DUPLICATED_CASE_NUMBERS: tuple[str, ...] = (
    "дело № 2-1234/2026",
    "Дело № 2-1234/2026",
    "дело №2-1234/2026",
    "гражданское дело № 2-1234/2026",
    "Гражданское дело № 2-1234/2026",
    "№ 2-1234/2026",
    "№2-1234/2026",
)


@pytest.mark.parametrize("case_number", DUPLICATED_CASE_NUMBERS)
def test_response_to_claim_never_duplicates_case_label(case_number: str) -> None:
    text = docx_text(build_response_to_claim_docx(_response(case_number=case_number)))

    assert not re.search(r"дело\s*№\s*(гражданское\s+)?дело\s*№", text, re.IGNORECASE), text[:400]
    assert not re.search(r"№\s*№", text), text[:400]
    assert text.lower().count("гражданское дело") == 1, text[:400]


@pytest.mark.parametrize("case_number", DUPLICATED_CASE_NUMBERS)
def test_response_to_claim_keeps_the_case_number_itself(case_number: str) -> None:
    """Дубликат снимается срезанием подписи, а не самого номера."""
    text = docx_text(build_response_to_claim_docx(_response(case_number=case_number)))

    assert "2-1234/2026" in text, text[:400]


def test_response_to_claim_keeps_bare_case_number_untouched() -> None:
    text = docx_text(build_response_to_claim_docx(_response(case_number="2-1234/2026")))

    assert "Гражданское дело № 2-1234/2026" in text


def test_response_to_claim_without_case_number_still_asks_for_it() -> None:
    """Пустой номер — это не выдумка факта: документ обязан попросить уточнение."""
    text = docx_text(build_response_to_claim_docx(_response(case_number="")))

    assert "Гражданское дело №" in text
    assert "ТРЕБУЕТ УТОЧНЕНИЯ" in text
