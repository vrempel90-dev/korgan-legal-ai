"""Отзыв на исковое заявление — DOCX export.

This is the document type where the numbering defect mutated worst: its body is
deliberately mixed, numbered objections interleaved with free narrative, and an
exporter that reaches for a Word list style per section turns every sentence
into a list item. Here the two are different block types, so the renderer in
korgan.docx_blocks can only number what is structural.
"""

from __future__ import annotations

import io
from datetime import datetime
from zoneinfo import ZoneInfo

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Cm, Pt

from korgan.docx_blocks import AutoNumberedList, Block, Heading, NumberedItem, Prose, render_blocks
from korgan.legal_types import ResponseDraft, VerificationStatus

DRAFT_NOTICE = (
    "Проект сформирован KORGAN Legal AI на основании материалов пользователя и проверенных правовых источников. "
    "Перед подачей необходимо проверить процессуальные сроки, доказательства и отмеченные системой вопросы."
)

OBJECTIONS_HEADING = "Возражения по существу заявленных требований"
LEGAL_BASIS_HEADING = "Правовое обоснование"


def _status(draft: ResponseDraft) -> str:
    body = "\n".join(draft.body_lines()).upper()
    if "[ТРЕБУЕТ УТОЧНЕНИЯ" in body or "[ТРЕБУЕТ ДОБАВИТЬ" in body:
        return "PRELIMINARY DRAFT"
    if draft.status == VerificationStatus.NEEDS_VERIFICATION or draft.verification_notes:
        return "LAWYER-REVIEW DRAFT"
    return "READY FOR FINAL HUMAN REVIEW"


def _today_kz() -> str:
    return datetime.now(ZoneInfo("Asia/Almaty")).strftime("%d.%m.%Y")


def _body_blocks(draft: ResponseDraft) -> list[Block]:
    blocks: list[Block] = [Prose(item) for item in draft.introduction]

    if draft.circumstances:
        blocks.append(Heading("Фактические обстоятельства"))
        blocks.extend(Prose(item) for item in draft.circumstances)

    if draft.objections:
        blocks.append(Heading(OBJECTIONS_HEADING))
        for objection in draft.objections:
            blocks.append(NumberedItem(objection.text, level=0))
            blocks.extend(NumberedItem(sub, level=1) for sub in objection.subclauses)
            # The paragraphs developing an objection stay narrative: they are
            # indented under it but carry no number of their own.
            blocks.extend(Prose(item, indent_levels=1) for item in objection.prose)

    if draft.legal_basis:
        blocks.append(Heading(LEGAL_BASIS_HEADING))
        blocks.extend(Prose(item) for item in draft.legal_basis)

    blocks.append(Heading("На основании изложенного ПРОШУ СУД:"))
    blocks.append(
        AutoNumberedList(
            list(draft.requests)
            or ["[ТРЕБУЕТ УТОЧНЕНИЯ: процессуальные требования ответчика]"]
        )
    )

    blocks.append(Heading("Приложения:"))
    blocks.append(
        AutoNumberedList(
            list(draft.attachments) or ["[ТРЕБУЕТ ДОБАВИТЬ: перечень приложений]"],
            restart=True,
        )
    )
    return blocks


def build_response_docx(draft: ResponseDraft) -> bytes:
    doc = Document()
    section = doc.sections[0]
    section.top_margin = Cm(2)
    section.bottom_margin = Cm(2)
    section.left_margin = Cm(2.5)
    section.right_margin = Cm(1.5)

    styles = doc.styles
    styles["Normal"].font.name = "Times New Roman"
    styles["Normal"].font.size = Pt(12)
    for name in ("Title", "Heading 1", "Heading 2"):
        if name in styles:
            styles[name].font.name = "Times New Roman"

    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = footer.add_run(DRAFT_NOTICE)
    run.font.name = "Times New Roman"
    run.font.size = Pt(8)

    qa = doc.add_paragraph()
    qa.alignment = WD_ALIGN_PARAGRAPH.CENTER
    qa_run = qa.add_run(f"KORGAN QA STATUS: {_status(draft)}")
    qa_run.bold = True
    qa_run.font.size = Pt(9)

    header = doc.add_paragraph()
    header.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    header.add_run(f"В суд: {draft.court or '[ТРЕБУЕТ УТОЧНЕНИЯ: наименование суда]'}\n").bold = True
    if draft.case_reference:
        header.add_run(f"Дело № {draft.case_reference}\n")
    header.add_run("Истец:\n").bold = True
    for item in draft.plaintiff or ["[ТРЕБУЕТ УТОЧНЕНИЯ: данные истца]"]:
        header.add_run(f"{item}\n")
    header.add_run("Ответчик:\n").bold = True
    for item in draft.defendant or ["[ТРЕБУЕТ УТОЧНЕНИЯ: данные ответчика]"]:
        header.add_run(f"{item}\n")

    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title_run = title.add_run((draft.title or "ОТЗЫВ НА ИСКОВОЕ ЗАЯВЛЕНИЕ").upper())
    title_run.bold = True
    title_run.font.size = Pt(14)

    render_blocks(doc, _body_blocks(draft))

    doc.add_paragraph()
    doc.add_paragraph(f"Дата: {_today_kz()}")
    doc.add_paragraph("Подпись: ____________________")

    stream = io.BytesIO()
    doc.save(stream)
    return stream.getvalue()
