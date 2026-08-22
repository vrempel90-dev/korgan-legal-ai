from __future__ import annotations

import io

from docx import Document

from korgan import claim_consistency_guard
from korgan.client_document_feedback_hotfix import checklist_text, material_law_issue
from korgan.legal_types import ClaimDraft, VerificationStatus
from korgan.pretrial_response import PretrialResponseDraft, build_pretrial_response_docx


def _claim(*, facts: list[str], legal_basis: list[str], requests: list[str]) -> ClaimDraft:
    return ClaimDraft(
        status=VerificationStatus.NEEDS_VERIFICATION,
        title="Исковое заявление",
        court="Суд",
        claimant=["Истец"],
        defendant=["Ответчик"],
        price_of_claim="500 000 тенге",
        facts=facts,
        legal_basis=legal_basis,
        requests=requests,
        attachments=["Договор"],
        verification_notes=[],
        source_urls=[],
    )


def test_pretrial_response_keeps_required_heading_when_reference_exists() -> None:
    draft = PretrialResponseDraft(
        status=VerificationStatus.VERIFIED,
        title="Модельный заголовок не должен управлять официальным заголовком",
        sender=["ТОО «Получатель»"],
        recipient=["ТОО «Заявитель»"],
        reference="исх. № 15 от 20.08.2026",
        claim_summary=["Получена претензия о взыскании 500 000 тенге."],
        position=["Заявленные требования не признаём по изложенным ниже основаниям."],
        objections=["Оплата подтверждена платёжными документами."],
        legal_basis=["Обязательства исполняются надлежащим образом согласно статье 272 ГК РК."],
        response_terms=["Просим учесть изложенную позицию."],
        attachments=["Платёжный документ"],
        verification_notes=[],
        source_urls=[],
    )

    payload = build_pretrial_response_docx(draft, language="ru")
    doc = Document(io.BytesIO(payload))
    paragraphs = [paragraph.text.strip() for paragraph in doc.paragraphs if paragraph.text.strip()]

    assert "ОТВЕТ НА ПРЕТЕНЗИЮ" in paragraphs
    assert any("исх. № 15" in value for value in paragraphs)
    assert paragraphs.index("ОТВЕТ НА ПРЕТЕНЗИЮ") < next(
        index for index, value in enumerate(paragraphs) if "исх. № 15" in value
    )


def test_material_law_issue_rejects_gpk_only_basis_when_civil_law_is_verified() -> None:
    issue = material_law_issue(
        ["Суд рассматривает дело по правилам статьи 148 ГПК РК."],
        ["Обязательства должны исполняться надлежащим образом согласно статье 272 ГК РК."],
        context="Спор возник из договора подряда и задолженности по оплате.",
        require_for_private_dispute=True,
    )

    assert issue is not None
    assert "материально" in issue.lower()


def test_material_law_issue_flags_private_dispute_when_research_has_only_procedure() -> None:
    issue = material_law_issue(
        ["Требования к иску определены статьёй 148 ГПК РК."],
        ["Требования к иску определены статьёй 148 ГПК РК."],
        context="По договору услуг заказчик требует возврат оплаты и неустойку.",
        require_for_private_dispute=True,
    )

    assert issue is not None
    assert "материально" in issue.lower()


def test_affirmative_penalty_in_body_cannot_disappear_from_prayer() -> None:
    draft = _claim(
        facts=["По договору начислена неустойка в размере 25 000 тенге, которая подлежит взысканию."],
        legal_basis=["Обязательства исполняются надлежащим образом согласно статье 272 ГК РК."],
        requests=["Взыскать основной долг 500 000 тенге."],
    )

    errors = claim_consistency_guard.claim_consistency_errors(
        "Истец требует взыскать основной долг по договору.",
        draft,
    )

    assert any("неустойка/пеня" in error and "ПРОШУ СУД" in error for error in errors)


def test_penalty_clause_mention_alone_does_not_force_unrequested_remedy() -> None:
    draft = _claim(
        facts=["Договор содержит условие о неустойке 0,1% за каждый день просрочки."],
        legal_basis=["Обязательства исполняются надлежащим образом согласно статье 272 ГК РК."],
        requests=["Взыскать основной долг 500 000 тенге."],
    )

    errors = claim_consistency_guard.claim_consistency_errors(
        "Истец просит взыскать только основной долг по договору.",
        draft,
    )

    assert not any("Текст иска утверждает, что неустойка/пеня" in error for error in errors)


def test_every_document_workflow_has_client_completion_checklist() -> None:
    for kind in ("claim", "pretrial", "pretrial_response", "contract", "response"):
        ru = checklist_text(kind, "ru")
        kk = checklist_text(kind, "kk")
        assert "📋" in ru
        assert "📋" in kk
        assert "придумывать" in ru
        assert "ойдан шығармайды" in kk

    assert "неустой" in checklist_text("claim", "ru").lower()
    assert "ОТВЕТ НА ПРЕТЕНЗИЮ" in checklist_text("pretrial_response", "ru")
    assert "ОТЗЫВ НА ИСК" in checklist_text("response", "ru")
