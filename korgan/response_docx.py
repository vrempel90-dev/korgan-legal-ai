from __future__ import annotations

import io

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Cm, Mm, Pt

from korgan.response_types import ResponseToClaimDraft


def _add_lines(doc: Document, lines: list[str]) -> None:
    for line in lines:
        value = str(line).strip()
        if not value:
            continue
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(3)
        p.add_run(value)


def _add_numbered(doc: Document, lines: list[str]) -> None:
    for idx, line in enumerate(lines, start=1):
        value = str(line).strip()
        if not value:
            continue
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(4)
        p.add_run(f"{idx}. {value}")


def build_response_to_claim_docx(draft: ResponseToClaimDraft) -> bytes:
    doc = Document()
    section = doc.sections[0]
    section.page_width = Mm(210)
    section.page_height = Mm(297)
    section.top_margin = Cm(2)
    section.bottom_margin = Cm(2)
    section.left_margin = Cm(2.5)
    section.right_margin = Cm(1.5)

    normal = doc.styles["Normal"]
    normal.font.name = "Times New Roman"
    normal.font.size = Pt(12)
    normal.paragraph_format.line_spacing = 1.15

    header = doc.add_paragraph()
    header.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    header.add_run(f"В {draft.court or '[ТРЕБУЕТ УТОЧНЕНИЯ: наименование суда]'}")

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    if draft.case_number:
        p.add_run(f"Гражданское дело № {draft.case_number}")
    else:
        p.add_run("Гражданское дело № [ТРЕБУЕТ УТОЧНЕНИЯ: номер дела, если присвоен]")

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    p.add_run("Истец:\n" + ("\n".join(draft.claimant) if draft.claimant else "[ТРЕБУЕТ УТОЧНЕНИЯ: ФИО/наименование и адрес]"))

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    p.add_run("Ответчик:\n" + ("\n".join(draft.defendant) if draft.defendant else "[ТРЕБУЕТ УТОЧНЕНИЯ: ФИО/наименование и адрес]"))

    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run(draft.title or "ОТЗЫВ НА ИСК")
    run.bold = True
    run.font.size = Pt(14)

    if draft.claim_summary:
        h = doc.add_paragraph()
        h.add_run("Краткое содержание заявленных требований").bold = True
        _add_lines(doc, draft.claim_summary)

    if draft.position:
        h = doc.add_paragraph()
        h.add_run("Позиция ответчика").bold = True
        _add_lines(doc, draft.position)

    h = doc.add_paragraph()
    h.add_run("Возражения по существу заявленных требований").bold = True
    if draft.objections:
        _add_numbered(doc, draft.objections)
    else:
        doc.add_paragraph("[ТРЕБУЕТ УТОЧНЕНИЯ: конкретные возражения ответчика по требованиям истца]")

    if draft.legal_basis:
        h = doc.add_paragraph()
        h.add_run("Правовое обоснование").bold = True
        _add_lines(doc, draft.legal_basis)

    h = doc.add_paragraph()
    h.add_run("На основании изложенного ПРОШУ СУД:").bold = True
    if draft.requests:
        _add_numbered(doc, draft.requests)
    else:
        doc.add_paragraph("[ТРЕБУЕТ УТОЧНЕНИЯ: процессуальная просьба ответчика]")

    h = doc.add_paragraph()
    h.add_run("Приложения:").bold = True
    if draft.attachments:
        _add_numbered(doc, draft.attachments)
    else:
        doc.add_paragraph("[ТРЕБУЕТ УТОЧНЕНИЯ: перечень прилагаемых документов]")

    doc.add_paragraph()
    sign = doc.add_paragraph()
    sign.add_run("Ответчик / представитель: ____________________    ")
    sign.add_run("Дата: ____________________")

    stream = io.BytesIO()
    doc.save(stream)
    return stream.getvalue()
