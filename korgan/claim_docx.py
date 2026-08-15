from __future__ import annotations

import io
from datetime import date

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Cm, Pt

from korgan.legal_types import ClaimDraft


DRAFT_NOTICE = (
    "Проект сформирован KORGAN Legal AI на основании материалов пользователя. "
    "Перед подачей необходимо проверить реквизиты, доказательства, подсудность, госпошлину и отмеченные системой вопросы. "
    "Формирование проекта не гарантирует принятие документа или исход дела."
)


def build_claim_docx(draft: ClaimDraft) -> bytes:
    """Build a clean court-facing DOCX; verification details stay in Telegram caption."""
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

    # Service/legal notice is intentionally unobtrusive and not mixed into the claim body.
    for current_section in doc.sections:
        footer = current_section.footer.paragraphs[0]
        footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = footer.add_run(DRAFT_NOTICE)
        run.font.name = "Times New Roman"
        run.font.size = Pt(8)

    right = doc.add_paragraph()
    right.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    right.add_run(f"В суд: {draft.court or '[ТРЕБУЕТ УТОЧНЕНИЯ: точное наименование суда]'}\n").bold = True
    right.add_run("Истец:\n").bold = True
    for item in draft.claimant or ["[ТРЕБУЕТ УТОЧНЕНИЯ: данные истца]"]:
        right.add_run(f"{item}\n")
    right.add_run("Ответчик:\n").bold = True
    for item in draft.defendant or ["[ТРЕБУЕТ УТОЧНЕНИЯ: данные ответчика]"]:
        right.add_run(f"{item}\n")
    right.add_run(f"Цена иска: {draft.price_of_claim or '[ТРЕБУЕТ УТОЧНЕНИЯ: цена иска]'}")

    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title_run = title.add_run(draft.title or "ИСКОВОЕ ЗАЯВЛЕНИЕ")
    title_run.bold = True
    title_run.font.name = "Times New Roman"
    title_run.font.size = Pt(14)

    for fact in draft.facts:
        paragraph = doc.add_paragraph(fact)
        paragraph.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY

    if draft.legal_basis:
        heading = doc.add_paragraph()
        heading.add_run("Правовое обоснование").bold = True
        for basis in draft.legal_basis:
            paragraph = doc.add_paragraph(basis)
            paragraph.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY

    request_heading = doc.add_paragraph()
    request_heading.add_run("На основании изложенного ПРОШУ СУД:").bold = True
    for request in draft.requests:
        doc.add_paragraph(request, style="List Number")

    attachments_heading = doc.add_paragraph()
    attachments_heading.add_run("Приложения:").bold = True
    for attachment in draft.attachments:
        doc.add_paragraph(attachment, style="List Number")

    doc.add_paragraph()
    doc.add_paragraph(f"Дата: {date.today().strftime('%d.%m.%Y')}")
    doc.add_paragraph("Подпись: ____________________")

    stream = io.BytesIO()
    doc.save(stream)
    return stream.getvalue()
