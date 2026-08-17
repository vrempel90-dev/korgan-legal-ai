from __future__ import annotations

import io
from datetime import datetime
from zoneinfo import ZoneInfo

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Cm, Pt

from korgan.docx_blocks import AutoNumberedList, Block, Heading, Prose, render_blocks
from korgan.legal_calc import NEEDS_CALCULATION_MARKER
from korgan.legal_types import ClaimDraft, VerificationStatus


DRAFT_NOTICE = (
    "Проект сформирован KORGAN Legal AI на основании материалов пользователя. "
    "Перед подачей необходимо проверить реквизиты, доказательства, подсудность, госпошлину и отмеченные системой вопросы. "
    "Формирование проекта не гарантирует принятие документа или исход дела."
)


QA_PRELIMINARY = "PRELIMINARY DRAFT"
QA_LAWYER_REVIEW = "LAWYER-REVIEW DRAFT"
QA_READY = "READY FOR FINAL HUMAN REVIEW"


REQUIRED_DOCUMENT_FIELDS: tuple[tuple[str, str], ...] = (
    ("claimant", "данные истца (ФИО/наименование, идентификатор, адрес)"),
    ("defendant", "данные ответчика (ФИО/наименование, адрес)"),
    ("facts", "обстоятельства дела"),
    ("requests", "требования к ответчику (просительная часть)"),
)


def _is_blank(value: object) -> bool:
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, list):
        return not [item for item in value if str(item).strip()]
    return not value


def missing_required_fields(draft: ClaimDraft) -> list[str]:
    return [
        label
        for attribute, label in REQUIRED_DOCUMENT_FIELDS
        if _is_blank(getattr(draft, attribute, None))
    ]


def _strip_label(value: str, label: str) -> str:
    text = value.strip()
    if text.lower().startswith(label.lower()):
        text = text[len(label):].lstrip(" : \t")
    return text.strip()


def _party_lines(items: list[str], label: str, fallback: str) -> list[str]:
    lines = [_strip_label(item, label) for item in items if item and item.strip()]
    return [line for line in lines if line] or [fallback]


def _document_status(draft: ClaimDraft) -> str:
    court_text = "\n".join(
        [
            draft.court,
            *draft.claimant,
            *draft.defendant,
            draft.price_of_claim,
            draft.state_duty,
            draft.late_interest,
            *draft.facts,
            *draft.legal_basis,
            *draft.requests,
            *draft.attachments,
        ]
    ).upper()

    if (
        "[ТРЕБУЕТ УТОЧНЕНИЯ" in court_text
        or "[ТРЕБУЕТ ДОБАВИТЬ" in court_text
        or "[ТРЕБУЕТ ПРОВЕРКИ" in court_text
        or NEEDS_CALCULATION_MARKER.upper() in court_text
    ):
        return QA_PRELIMINARY

    if draft.status == VerificationStatus.NEEDS_VERIFICATION or draft.verification_notes:
        return QA_LAWYER_REVIEW

    return QA_READY


def _kazakhstan_today() -> str:
    return datetime.now(ZoneInfo("Asia/Almaty")).strftime("%d.%m.%Y")


def _body_blocks(draft: ClaimDraft) -> list[Block]:
    """Describe the claim body.

    Facts and legal reasoning are narrative: they are `Prose` and therefore can
    never pick up a list number. Only просительная часть and приложения are real
    numbered lists, and приложения restart at 1.
    """
    blocks: list[Block] = [Prose(fact) for fact in draft.facts]

    if draft.legal_basis:
        blocks.append(Heading("Правовое обоснование"))
        blocks.extend(Prose(basis) for basis in draft.legal_basis)

    if draft.late_interest:
        blocks.append(Heading("Расчёт неустойки по статье 353 ГК РК"))
        blocks.append(Prose(draft.late_interest))

    blocks.append(Heading("На основании изложенного ПРОШУ СУД:"))
    blocks.append(AutoNumberedList(list(draft.requests)))

    blocks.append(Heading("Приложения:"))
    blocks.append(AutoNumberedList(list(draft.attachments), restart=True))
    return blocks


def build_claim_docx(draft: ClaimDraft) -> bytes:
    """Build a clean court-facing DOCX.

    Internal KORGAN QA labels are shown only on a preliminary/lawyer-review
    project. A release-ready claim must look like a normal court document, not
    like an internal AI report.
    """
    doc = Document()

    section = doc.sections[0]
    section.top_margin = Cm(2)
    section.bottom_margin = Cm(2)
    section.left_margin = Cm(2.5)
    section.right_margin = Cm(1.5)

    styles = doc.styles
    styles["Normal"].font.name = "Times New Roman"
    styles["Normal"].font.size = Pt(12)
    for style_name in ("Title", "Heading 1", "Heading 2"):
        if style_name in styles:
            styles[style_name].font.name = "Times New Roman"

    document_status = _document_status(draft)
    if document_status != QA_READY:
        for current_section in doc.sections:
            footer = current_section.footer.paragraphs[0]
            footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = footer.add_run(DRAFT_NOTICE)
            run.font.name = "Times New Roman"
            run.font.size = Pt(8)

        qa = doc.add_paragraph()
        qa.alignment = WD_ALIGN_PARAGRAPH.CENTER
        qa_run = qa.add_run(f"KORGAN QA STATUS: {document_status}")
        qa_run.bold = True
        qa_run.font.name = "Times New Roman"
        qa_run.font.size = Pt(9)

    court = _strip_label(draft.court, "В суд") or "[ТРЕБУЕТ УТОЧНЕНИЯ: точное наименование суда]"
    price = _strip_label(draft.price_of_claim, "Цена иска") or "[ТРЕБУЕТ УТОЧНЕНИЯ: цена иска]"

    right = doc.add_paragraph()
    right.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    right.add_run(f"В суд: {court}\n").bold = True
    right.add_run("Истец:\n").bold = True
    for item in _party_lines(draft.claimant, "Истец", "[ТРЕБУЕТ УТОЧНЕНИЯ: данные истца]"):
        right.add_run(f"{item}\n")
    right.add_run("Ответчик:\n").bold = True
    for item in _party_lines(draft.defendant, "Ответчик", "[ТРЕБУЕТ УТОЧНЕНИЯ: данные ответчика]"):
        right.add_run(f"{item}\n")
    right.add_run(f"Цена иска: {price}\n")
    duty = _strip_label(draft.state_duty, "Госпошлина") or NEEDS_CALCULATION_MARKER
    right.add_run(f"Госпошлина: {duty}")

    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title_run = title.add_run(draft.title or "ИСКОВОЕ ЗАЯВЛЕНИЕ")
    title_run.bold = True
    title_run.font.name = "Times New Roman"
    title_run.font.size = Pt(14)

    render_blocks(doc, _body_blocks(draft))

    doc.add_paragraph()
    doc.add_paragraph(f"Дата: {_kazakhstan_today()}")
    doc.add_paragraph("Подпись: ____________________")

    stream = io.BytesIO()
    doc.save(stream)
    return stream.getvalue()
