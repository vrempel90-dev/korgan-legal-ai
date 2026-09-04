"""Договорная неустойка излагается словами договора и не выдаётся за статью 353.

Два дефекта, которые видел бы судья в готовом иске:

1. раздел расчёта договорной неустойки печатался под заголовком «Расчёт
   неустойки по статье 353 ГК РК». Ставка при этом договорная — документ
   называл законное основание, которого требование не имеет;
2. база неустойки во всех формулировках подменялась на «от суммы
   задолженности», хотя договор считает её от иной величины — «от стоимости
   невыполненного обязательства». Для заказчика, оплатившего работу вперёд,
   это разные суммы, и подмена меняет смысл условия договора.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from korgan.claim_docx import build_claim_docx
from korgan.contractual_penalty import parse_contractual_penalty_terms
from korgan.document_quality import docx_text
from korgan.legal_types import ClaimDraft, VerificationStatus

WORK_CLAUSE = (
    "Пунктом 5.2 договора предусмотрено: при нарушении срока выполнения работ исполнитель "
    "выплачивает заказчику неустойку в размере 0,1 % от стоимости невыполненного обязательства "
    "за каждый день просрочки, но не более 10 % стоимости договора."
)


def _draft(late_interest: str) -> ClaimDraft:
    return ClaimDraft(
        status=VerificationStatus.NEEDS_VERIFICATION,
        title="Исковое заявление",
        court="районный суд № 2 Алмалинского района города Алматы",
        claimant=["Сериков Арман Нурланович"],
        defendant=["ТОО «Мебель Стандарт»"],
        price_of_claim="1 292 400 тенге",
        facts=["Работы не выполнены."],
        legal_basis=[],
        requests=["Взыскать 1 200 000 тенге."],
        attachments=["Договор № MS-114/26."],
        verification_notes=[],
        source_urls=[],
        late_interest=late_interest,
    )


def test_contractual_penalty_section_is_not_titled_article_353() -> None:
    draft = _draft(
        "92 400 тенге за период с 16.06.2026 по 31.08.2026 (77 дн.; договорная ставка 0,1 % "
        "от стоимости невыполненного обязательства за каждый день просрочки; пункт 5.2 договора)"
    )

    body = docx_text(build_claim_docx(draft))

    assert "Расчёт договорной неустойки" in body
    assert "353" not in body


def test_article_353_section_keeps_its_own_title() -> None:
    draft = _draft(
        "36 391 тенге за период с 16.06.2026 по 31.08.2026 (77 дн.; статья 353 ГК РК; "
        "базовая ставка НБ РК 17%)"
    )

    body = docx_text(build_claim_docx(draft))

    assert "Расчёт неустойки по статье 353 ГК РК" in body


def test_contract_base_of_the_penalty_is_carried_into_the_terms() -> None:
    terms = parse_contractual_penalty_terms(WORK_CLAUSE)

    assert terms is not None
    assert terms.base_label == "стоимости невыполненного обязательства"


def test_missing_contract_base_falls_back_to_the_neutral_wording() -> None:
    terms = parse_contractual_penalty_terms(
        "Пункт 6.3 договора: неустойка 0,1% за каждый день просрочки."
    )

    assert terms is not None
    assert terms.base_label == ""


def test_penalty_rate_is_written_with_a_decimal_comma() -> None:
    """В юридическом тексте на русском десятичный разделитель — запятая."""
    from korgan.late_interest_hotfix import _contractual_penalty_line
    from korgan.contractual_penalty import calc_contractual_penalty

    terms = parse_contractual_penalty_terms(WORK_CLAUSE)
    assert terms is not None
    penalty = calc_contractual_penalty(1_200_000, terms, date(2026, 6, 16), date(2026, 8, 31))

    line = _contractual_penalty_line(penalty)

    assert "0,1%" in line
    assert "0.1%" not in line
    assert "стоимости невыполненного обязательства" in line


def test_kazakh_document_gets_the_contractual_heading_too() -> None:
    """Заголовок выбирается по исходной русской строке расчёта, а не по переводу."""
    from korgan.claim_docx import _penalty_heading

    contractual = (
        "92 400 тенге за период с 16.06.2026 по 31.08.2026 (77 дн.; договорная ставка 0,1 % "
        "от стоимости невыполненного обязательства за каждый день просрочки; пункт 5.2 договора)"
    )
    article_353 = "36 391 тенге (статья 353 ГК РК; базовая ставка НБ РК 17%)"

    assert _penalty_heading(contractual, kk=True) == "Шарттық тұрақсыздық айыбының есебі"
    assert _penalty_heading(article_353, kk=True) == "ҚР АК 353-бабы бойынша есеп"
