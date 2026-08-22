from __future__ import annotations

import io

from docx import Document

from korgan.client_document_feedback_hotfix import (
    affirmative_penalty_statement,
    checklist_text,
    material_law_issue,
    remedy_support_issues,
)
from korgan.legal_types import VerificationStatus
from korgan.pretrial_response import PretrialResponseDraft, build_pretrial_response_docx


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
        legal_basis=["Материальная норма подтверждена официальным источником."],
        response_terms=["Просим учесть изложенную позицию."],
        attachments=["Платёжный документ"],
        verification_notes=[],
        source_urls=[],
    )
    payload = build_pretrial_response_docx(draft, language="ru")
    paragraphs = [p.text.strip() for p in Document(io.BytesIO(payload)).paragraphs if p.text.strip()]
    assert "ОТВЕТ НА ПРЕТЕНЗИЮ" in paragraphs
    assert paragraphs.index("ОТВЕТ НА ПРЕТЕНЗИЮ") < next(
        index for index, value in enumerate(paragraphs) if "исх. № 15" in value
    )


def test_material_law_issue_rejects_procedure_only_private_dispute() -> None:
    issue = material_law_issue(
        ["Требования к иску определены статьёй 148 ГПК РК."],
        ["Требования к иску определены статьёй 148 ГПК РК."],
        context="Спор возник из договора услуг и возврата оплаты.",
        require_for_private_dispute=True,
    )
    assert issue is not None
    assert "материально" in issue.lower()


def test_verified_special_statute_counts_as_material_support() -> None:
    verified = [
        "Специальное право поддерживает требование "
        "[основание: статья 10 Закона Республики Казахстан «Тестовый специальный закон»; "
        "текст нормы: тест; источник: https://adilet.zan.kz/test]"
    ]
    issue = material_law_issue(
        ["Основание требования: статья 10 Закона Республики Казахстан «Тестовый специальный закон»."],
        verified,
        context="Спор возник из договора оказания услуг.",
        require_for_private_dispute=True,
    )
    assert issue is None


def test_penalty_negations_are_not_affirmative() -> None:
    assert not affirmative_penalty_statement("Неустойка не подлежит взысканию.")
    assert not affirmative_penalty_statement("Неустойка не начислена.")
    assert not affirmative_penalty_statement(
        "Договорная неустойка составляет 0,1%, но истец её не требует."
    )


def test_explicit_penalty_collection_is_affirmative() -> None:
    assert affirmative_penalty_statement("Истец требует взыскать неустойку.")
    assert affirmative_penalty_statement("Истец просит взыскать пеню в установленном размере.")
    assert affirmative_penalty_statement("Неустойка начислена и подлежит взысканию.")


def test_each_independent_remedy_needs_its_own_verified_material_support() -> None:
    issues = remedy_support_issues(
        ["Взыскать основной долг 500 000 тенге.", "Взыскать неустойку 25 000 тенге."],
        ["Основание основного требования: статья 1 Кодекса TEST."],
        [
            "Обязательство должно исполняться надлежащим образом "
            "[основание: статья 1 Кодекса TEST; текст нормы: тест; источник: https://adilet.zan.kz/test]"
        ],
    )
    assert any("неустойки/пени/штрафа" in issue and "VERIFIED" in issue for issue in issues)


def test_separate_verified_penalty_support_clears_per_remedy_issue() -> None:
    issues = remedy_support_issues(
        ["Взыскать основной долг 500 000 тенге.", "Взыскать неустойку 25 000 тенге."],
        [
            "Основание основного требования: статья 1 Кодекса TEST.",
            "Основание неустойки: статья 2 Кодекса TEST.",
        ],
        [
            "Обязательство должно исполняться надлежащим образом "
            "[основание: статья 1 Кодекса TEST; текст нормы: тест; источник: https://adilet.zan.kz/test]",
            "Неустойка может быть взыскана при подтвержденных условиях "
            "[основание: статья 2 Кодекса TEST; текст нормы: тест; источник: https://adilet.zan.kz/test]",
        ],
    )
    assert not issues


def test_every_document_workflow_has_client_completion_checklist() -> None:
    for kind in ("claim", "pretrial", "pretrial_response", "contract", "response"):
        ru = checklist_text(kind, "ru")
        kk = checklist_text(kind, "kk")
        assert "📋" in ru
        assert "📋" in kk
        assert "придумывать" in ru
        assert "ойдан шығармайды" in kk
    assert "неустой" in checklist_text("claim", "ru").lower()
    assert "ОТВЕТА НА ПРЕТЕНЗИЮ" in checklist_text("pretrial_response", "ru")
    assert "ОТЗЫВА НА ИСК" in checklist_text("response", "ru")
