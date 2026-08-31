"""Досудебная претензия — самостоятельный документ, а не сокращённый иск.

Проверяется профессиональный минимум: денежное требование раскрыто расчётом,
срок исполнения не выдуман, требование конкретно, а качество имеет численную
оценку — как у иска, договора и отзыва, а не список замечаний без порога.
"""

from __future__ import annotations

from io import BytesIO

from docx import Document

from korgan.document_quality import assess_document_quality
from korgan.legal_types import LegalResearch, VerificationStatus
from korgan.provision_check import verified_claim_line
from korgan.pretrial import (
    PretrialDraft,
    build_pretrial_docx,
    pretrial_quality_issues,
)

GK_URL = "https://adilet.zan.kz/rus/docs/K990000409_"
GK_GENERAL_URL = "https://adilet.zan.kz/rus/docs/K940001000_"
ARTICLE_623 = (
    "Заказчик обязан уплатить подрядчику обусловленную цену после окончательной сдачи "
    "результатов работы при условии, что работа выполнена надлежащим образом и в согласованный срок."
)
ARTICLE_293 = (
    "Неустойкой (штрафом, пеней) признается определенная законодательством или договором денежная сумма, "
    "которую должник обязан уплатить кредитору в случае неисполнения или ненадлежащего исполнения обязательства."
)


def _research(*verified: str) -> LegalResearch:
    # Договорная неустойка — самостоятельное требование, и у него должно быть
    # собственное подтверждённое основание, а не только норма об оплате работ.
    claims = list(verified) or [
        verified_claim_line(
            "Заказчик обязан оплатить принятые работы",
            "статья 623 ГК РК",
            ARTICLE_623,
            GK_URL,
        ),
        verified_claim_line(
            "Стороны вправе согласовать неустойку за нарушение обязательства",
            "статья 293 ГК РК",
            ARTICLE_293,
            GK_GENERAL_URL,
        ),
    ]
    return LegalResearch(
        status=VerificationStatus.VERIFIED,
        applicable_law=[],
        procedural_requirements=[],
        verified_claims=claims,
        unverified_claims=[],
        source_urls=[GK_URL, GK_GENERAL_URL],
        notes=[],
    )


def _draft(**overrides) -> PretrialDraft:
    data = dict(
        status=VerificationStatus.VERIFIED,
        title="ДОСУДЕБНАЯ ПРЕТЕНЗИЯ",
        sender=['ТОО «Астана Строй», БИН 123456789012, г. Астана, ул. Кенесары, 40'],
        recipient=['ТОО «Заказчик», БИН 210987654321, г. Астана, ул. Абая, 15'],
        facts=[
            "Между сторонами заключён договор подряда № 12 от 15.01.2026.",
            "Работы приняты по акту от 20.02.2026, оплата в размере 2 300 000 тенге не произведена.",
        ],
        legal_basis=[
            f"{ARTICLE_623} Правовое основание: статья 623 ГК РК.",
            f"{ARTICLE_293} Правовое основание: статья 293 ГК РК.",
        ],
        demands=["Оплатить задолженность в размере 2 300 000 тенге и договорную неустойку 71 300 тенге."],
        deadline="10 календарных дней с даты получения настоящей претензии",
        consequences=["При неисполнении требований спор будет передан на разрешение суда."],
        attachments=["Копия договора подряда № 12 от 15.01.2026", "Копия акта от 20.02.2026"],
        verification_notes=[],
        source_urls=[GK_URL],
        calculation=[
            "Основной долг: 2 300 000 тенге; основание: договор подряда № 12 от 15.01.2026.",
            "Договорная неустойка: 71 300 тенге; основание: пункт 6.3 договора; база: 2 300 000 тенге; "
            "ставка: 0.1% за каждый день просрочки; период: с 01.03.2026 по 31.03.2026; дней: 31; "
            "расчёт: 2 300 000 тенге × 0.1% × 31 дн. = 71 300 тенге.",
        ],
    )
    data.update(overrides)
    return PretrialDraft(**data)


def _docx_text(draft: PretrialDraft, language: str = "ru") -> str:
    document = Document(BytesIO(build_pretrial_docx(draft, language=language)))
    return "\n".join(p.text for p in document.paragraphs)


# --- расчёт ---------------------------------------------------------------


def test_pretrial_draft_carries_a_calculation_section() -> None:
    draft = _draft()
    assert draft.calculation
    assert pretrial_quality_issues(draft, _research()) == []


def test_money_demand_without_a_calculation_is_blocked() -> None:
    draft = _draft(calculation=[])
    issues = pretrial_quality_issues(draft, _research())
    assert any("расчёт" in issue.lower() for issue in issues)


def test_non_money_demand_does_not_require_a_calculation() -> None:
    draft = _draft(
        demands=["Устранить недостатки выполненных работ, перечисленные в акте от 20.02.2026."],
        calculation=[],
    )
    assert not any("расчёт" in issue.lower() for issue in pretrial_quality_issues(draft, _research()))


def test_calculation_is_rendered_into_the_word_file() -> None:
    body = _docx_text(_draft())
    assert "Расчёт задолженности" in body
    assert "2 300 000 тенге × 0.1% × 31 дн. = 71 300 тенге" in body


def test_word_file_has_no_calculation_heading_without_a_calculation() -> None:
    body = _docx_text(_draft(calculation=[], demands=["Устранить недостатки работ."]))
    assert "Расчёт задолженности" not in body


# --- срок и содержательность ---------------------------------------------


def test_missing_deadline_is_reported() -> None:
    issues = pretrial_quality_issues(_draft(deadline=""), _research())
    assert any("срок" in issue.lower() for issue in issues)


def test_empty_threat_without_legal_consequence_is_blocked() -> None:
    draft = _draft(consequences=["Мы примем меры."])
    issues = pretrial_quality_issues(draft, _research())
    assert any("последств" in issue.lower() for issue in issues)


def test_lawful_consequence_passes() -> None:
    draft = _draft(consequences=["При неисполнении требований спор будет передан на разрешение суда."])
    assert not any("последств" in issue.lower() for issue in pretrial_quality_issues(draft, _research()))


# --- численная оценка качества -------------------------------------------


def test_pretrial_has_a_numeric_quality_score() -> None:
    report = assess_document_quality("pretrial", "материалы дела", _research(), _draft())
    assert report.kind == "pretrial"
    assert report.score == 10.0
    assert report.ready is True


def test_incomplete_pretrial_cannot_reach_the_ready_score() -> None:
    draft = _draft(calculation=[], recipient=[], legal_basis=[])
    report = assess_document_quality("pretrial", "материалы дела", _research(), draft)
    assert report.ready is False
    assert report.score < 10.0
    assert report.hard_blockers


def test_internal_terminology_never_reaches_the_pretrial_body() -> None:
    draft = _draft(facts=["NEEDS_VERIFICATION: уточнить дату акта."])
    report = assess_document_quality("pretrial", "материалы дела", _research(), draft)
    assert report.ready is False
