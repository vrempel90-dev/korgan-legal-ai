from __future__ import annotations

import io

from docx import Document

from korgan.claim_docx import build_claim_docx
from korgan.legal_types import ClaimDraft, VerificationStatus
from korgan.pro_claim_sections import PRO_CLAIM_PROMPT, pro_payload, pro_text


def _draft() -> ClaimDraft:
    return ClaimDraft(
        status=VerificationStatus.VERIFIED,
        title="ИСКОВОЕ ЗАЯВЛЕНИЕ о взыскании задолженности и договорной неустойки",
        court="Районный суд",
        claimant=["Истец"],
        defendant=["Ответчик"],
        price_of_claim="1 100 000 тенге",
        facts=["Между сторонами заключён договор аренды."],
        legal_basis=["Ответчик нарушил обязанность по оплате по договору."],
        requests=[
            "Взыскать основной долг 1 000 000 тенге.",
            "Взыскать договорную неустойку 100 000 тенге.",
            "Взыскать расходы на юридические услуги 50 000 тенге.",
        ],
        attachments=["Договор аренды"],
        verification_notes=[],
        source_urls=[],
        state_duty="10 000 тенге",
        jurisdiction_reason="Иск предъявляется по месту нахождения ответчика.",
        calculation=[
            "Основной долг: 1 000 000 тенге.",
            "Договорная неустойка: 1 000 000 × 0,1% × 100 дней = 100 000 тенге.",
            "Расходы на юридические услуги: 50 000 тенге по договору оказания юридической помощи.",
        ],
        pretrial_compliance="Претензия направлена ответчику.",
        reconciliation_measures="",
        limitation_period="Срок исковой давности не истёк.",
        anticipated_defenses=[
            "Ответчик может утверждать, что расчёт неверен — однако истец считает иначе."
        ],
        motions=[],
    )


def test_predicted_defenses_are_never_rendered_into_claim_docx() -> None:
    data = build_claim_docx(_draft())
    doc = Document(io.BytesIO(data))
    text = "\n".join(paragraph.text for paragraph in doc.paragraphs)

    assert "Расчёт взыскиваемых сумм" in text
    assert "Договорная неустойка" in text
    assert "Расходы на юридические услуги" in text
    assert "Возражения ответчика" not in text
    assert "Ответчик может утверждать" not in text


def test_anticipated_defenses_are_internal_compatibility_only() -> None:
    draft = _draft()
    assert pro_payload(draft)["anticipated_defenses"] == []
    assert all("Ответчик может утверждать" not in item for item in pro_text(draft))


def test_prompt_requires_money_breakdown_and_forbids_predicted_defense_section() -> None:
    assert "ДОГОВОРНОЙ неустойки" in PRO_CLAIM_PROMPT
    assert "расходы на юридические услуги/представителя" in PRO_CLAIM_PROMPT
    assert "ВСЕГДА возвращай пустой" in PRO_CLAIM_PROMPT
    assert "Не создавай в исковом заявлении раздел «Возражения ответчика»" in PRO_CLAIM_PROMPT
