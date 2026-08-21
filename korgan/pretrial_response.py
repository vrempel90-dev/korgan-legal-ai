"""Dedicated answer-to-pretrial-demand document flow.

This module is intentionally separate from both:
- the outgoing pre-trial demand (досудебная претензия), and
- the court response to a statement of claim (отзыв на иск).

Keeping a separate draft type, intent and DOCX renderer prevents one menu item
from accidentally producing another legal document type.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from typing import Any

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Cm, Pt

from korgan.document_release import review_lines
from korgan.legal_types import LegalResearch, VerificationStatus

_ACTION = re.compile(
    r"(?i)\b(?:подготов\w*|состав\w*|сформир\w*|сдел\w*|напиш\w*|напис\w*|созда\w*|"
    r"дайында\w*|жаса\w*|әзірле\w*|құрастыр\w*|жаз\w*)\b"
)
_RESPONSE_TO_PRETRIAL = re.compile(
    r"(?i)(?:"
    r"\bответ\w*\b.{0,24}\bна\s+(?:досудебн\w*\s+)?претензи\w*\b|"
    r"\bвозражен\w*\b.{0,24}\bна\s+(?:досудебн\w*\s+)?претензи\w*\b|"
    r"\b(?:досудебн\w*\s+)?претензи\w*\b.{0,24}\bответ\w*\b|"
    r"\bсотқа\s+дейінгі\s+талап\w*\b.{0,24}\bжауап\w*\b|"
    r"\bталап\s+хат\w*\b.{0,24}\bжауап\w*\b|"
    r"\bжауап\w*\b.{0,24}\bсотқа\s+дейінгі\s+талап\w*\b|"
    r"\bжауап\w*\b.{0,24}\bталап\s+хат\w*\b"
    r")"
)

_PRETRIAL_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "sender": {"type": "array", "items": {"type": "string"}},
        "recipient": {"type": "array", "items": {"type": "string"}},
        "incoming_claim": {"type": "array", "items": {"type": "string"}},
        "position": {"type": "array", "items": {"type": "string"}},
        "arguments": {"type": "array", "items": {"type": "string"}},
        "legal_basis": {"type": "array", "items": {"type": "string"}},
        "response": {"type": "array", "items": {"type": "string"}},
        "attachments": {"type": "array", "items": {"type": "string"}},
        "verification_notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "title",
        "sender",
        "recipient",
        "incoming_claim",
        "position",
        "arguments",
        "legal_basis",
        "response",
        "attachments",
        "verification_notes",
    ],
    "additionalProperties": False,
}


def is_pretrial_response_request(text: str | None) -> bool:
    value = " ".join((text or "").split())
    return bool(value and _ACTION.search(value) and _RESPONSE_TO_PRETRIAL.search(value))


@dataclass(slots=True)
class PretrialResponseDraft:
    status: VerificationStatus
    title: str
    sender: list[str]
    recipient: list[str]
    incoming_claim: list[str]
    position: list[str]
    arguments: list[str]
    legal_basis: list[str]
    response: list[str]
    attachments: list[str]
    verification_notes: list[str] = field(default_factory=list)
    source_urls: list[str] = field(default_factory=list)

    def body_lines(self) -> list[str]:
        return [
            self.title,
            *self.sender,
            *self.recipient,
            *self.incoming_claim,
            *self.position,
            *self.arguments,
            *self.legal_basis,
            *self.response,
            *self.attachments,
        ]


def pretrial_response_quality_issues(draft: PretrialResponseDraft, research: LegalResearch) -> list[str]:
    issues: list[str] = []
    if not draft.incoming_claim:
        issues.append("не отражено содержание полученной претензии")
    if not draft.position:
        issues.append("не сформулирована позиция адресата претензии")
    if not draft.response:
        issues.append("нет итогового ответа на требования претензии")
    report = review_lines(draft.body_lines(), verified_claims=research.verified_claims)
    issues.extend(report.blocking)
    return list(dict.fromkeys(issues))


async def generate_pretrial_response(
    service: Any,
    case_context: str,
    *,
    language: str = "ru",
) -> tuple[PretrialResponseDraft, LegalResearch]:
    """Generate only an answer to an incoming pre-trial demand.

    Existing source-bound legal research is reused, while the drafting schema and
    instructions are document-specific. No existing claim/pretrial/response
    generator is modified or reused as a renderer.
    """
    research_method = getattr(service, "research_case", None)
    structured_method = getattr(service, "_structured_response", None)
    if research_method is None or structured_method is None:
        raise RuntimeError("Pretrial response generation is unavailable in this service")

    research = await research_method(case_context, language=language)
    verified = "\n".join(f"- {item}" for item in research.verified_claims) or "- нет подтвержденных норм"
    prompt = (
        "Подготовь профессиональный ОТВЕТ НА ПОЛУЧЕННУЮ ДОСУДЕБНУЮ ПРЕТЕНЗИЮ по праву Республики Казахстан. "
        "Это отдельный документ: НЕ досудебная претензия, НЕ исковое заявление и НЕ отзыв на иск.\n\n"
        "Правила:\n"
        "1. Отвечай только на требования входящей претензии, которые реально есть в материалах.\n"
        "2. Не меняй роли сторон: отправитель ответа — адресат полученной претензии; получатель ответа — отправитель претензии.\n"
        "3. Не придумывай признание долга, оплату, договор, даты, суммы, переписку, доказательства или иные факты.\n"
        "4. Если позиция пользователя по конкретному требованию неясна, не признавай его автоматически; укажи нейтральную формулировку и добавь замечание о необходимости проверки.\n"
        "5. Используй только VERIFIED-нормы из исследования. Неподтвержденные статьи не вставляй как действующее право.\n"
        "6. Итоговый раздел response должен по каждому требованию ясно показывать: признается, отклоняется полностью/частично либо требуется уточнение.\n"
        "7. Не превращай ответ на претензию во встречную претензию и не добавляй самостоятельные требования без прямого указания пользователя.\n"
        "8. В приложениях перечисляй только материалы, которые реально есть в контексте.\n"
        f"9. Язык документа: {'казахский' if language == 'kk' else 'русский'}.\n\n"
        f"МАТЕРИАЛЫ ДЕЛА:\n{case_context}\n\n"
        f"VERIFIED:\n{verified}"
    )
    payload, _ = await structured_method(
        model=service.settings.openai_model,
        instructions=(
            "Ты практикующий юрист KORGAN в Республике Казахстан. "
            "Составляй только ответ на входящую досудебную претензию. "
            "Не подменяй его иском, отзывом на иск или новой претензией."
        ),
        content=[{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
        schema_name="korgan_pretrial_response",
        schema=_PRETRIAL_RESPONSE_SCHEMA,
    )
    draft = PretrialResponseDraft(
        status=research.status,
        source_urls=list(research.source_urls),
        **payload,
    )
    issues = pretrial_response_quality_issues(draft, research)
    if issues:
        draft.status = VerificationStatus.NEEDS_VERIFICATION
        for issue in issues:
            if issue not in draft.verification_notes:
                draft.verification_notes.append(issue)
    return draft, research


def build_pretrial_response_docx(draft: PretrialResponseDraft, *, language: str = "ru") -> bytes:
    kk = language == "kk"
    doc = Document()
    section = doc.sections[0]
    section.top_margin = Cm(2)
    section.bottom_margin = Cm(2)
    section.left_margin = Cm(2.5)
    section.right_margin = Cm(1.5)
    doc.styles["Normal"].font.name = "Times New Roman"
    doc.styles["Normal"].font.size = Pt(12)

    head = doc.add_paragraph()
    head.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    head.add_run(("Жіберуші:\n" if kk else "От:\n")).bold = True
    for value in draft.sender or [("[Жіберуші деректері]" if kk else "[Данные отправителя ответа]")]:
        head.add_run(str(value) + "\n")
    head.add_run(("Алушы:\n" if kk else "Кому:\n")).bold = True
    for value in draft.recipient or [("[Алушы деректері]" if kk else "[Данные получателя ответа]")]:
        head.add_run(str(value) + "\n")

    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    default_title = "СОТҚА ДЕЙІНГІ ТАЛАПҚА ЖАУАП" if kk else "ОТВЕТ НА ДОСУДЕБНУЮ ПРЕТЕНЗИЮ"
    run = title.add_run(draft.title or default_title)
    run.bold = True
    run.font.size = Pt(14)

    sections = [
        ("Алынған талаптың мазмұны" if kk else "Содержание полученной претензии", draft.incoming_claim),
        ("Позиция" if kk else "Позиция", draft.position),
        ("Негіздемелер" if kk else "Возражения и доводы", draft.arguments),
        ("Құқықтық негіздеме" if kk else "Правовое обоснование", draft.legal_basis),
        ("Жауап" if kk else "Ответ по существу требований", draft.response),
    ]
    for heading, lines in sections:
        if not lines:
            continue
        p = doc.add_paragraph()
        p.add_run(heading).bold = True
        for line in lines:
            doc.add_paragraph(str(line))

    if draft.attachments:
        p = doc.add_paragraph()
        p.add_run("Қосымшалар:" if kk else "Приложения:").bold = True
        for index, item in enumerate(draft.attachments, 1):
            doc.add_paragraph(f"{index}. {item}")

    doc.add_paragraph()
    doc.add_paragraph("Қолы: ____________________" if kk else "Подпись: ____________________")

    stream = io.BytesIO()
    doc.save(stream)
    return stream.getvalue()
