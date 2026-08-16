from __future__ import annotations

import io
from datetime import datetime
from zoneinfo import ZoneInfo

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Cm, Pt

from korgan.contract_numbering import iter_numbered_paragraphs
from korgan.contract_preamble import ensure_identified_preamble
from korgan.legal_types import ContractDraft, VerificationStatus


DRAFT_NOTICE = (
    "Проект сформирован KORGAN Legal AI на основании материалов пользователя и проверенных правовых источников. "
    "Перед подписанием необходимо проверить реквизиты сторон, коммерческие условия и отмеченные системой вопросы."
)


def _status(draft: ContractDraft, preamble: list[str]) -> str:
    body = "\n".join([*draft.body_lines(), *preamble]).upper()
    if "[ТРЕБУЕТ УТОЧНЕНИЯ" in body:
        return "PRELIMINARY DRAFT"
    if draft.status == VerificationStatus.NEEDS_VERIFICATION or draft.verification_notes:
        return "LAWYER-REVIEW DRAFT"
    return "READY FOR FINAL HUMAN REVIEW"


def _today_kz() -> str:
    return datetime.now(ZoneInfo("Asia/Almaty")).strftime("%d.%m.%Y")


def build_contract_docx(draft: ContractDraft) -> bytes:
    doc = Document()
    section = doc.sections[0]
    section.top_margin = Cm(2)
    section.bottom_margin = Cm(2)
    section.left_margin = Cm(2.2)
    section.right_margin = Cm(1.8)

    styles = doc.styles
    styles["Normal"].font.name = "Times New Roman"
    styles["Normal"].font.size = Pt(11)
    for name in ("Title", "Heading 1", "Heading 2"):
        if name in styles:
            styles[name].font.name = "Times New Roman"

    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = footer.add_run(DRAFT_NOTICE)
    run.font.name = "Times New Roman"
    run.font.size = Pt(8)

    # The identification block is mandatory: when the model omitted it, the
    # export inserts the structure with visible gaps instead of shipping a
    # contract whose parties are only named in the requisites table.
    preamble = ensure_identified_preamble(
        draft.preamble,
        party_a=draft.party_a,
        party_b=draft.party_b,
    )

    qa = doc.add_paragraph()
    qa.alignment = WD_ALIGN_PARAGRAPH.CENTER
    qa_run = qa.add_run(f"KORGAN QA STATUS: {_status(draft, preamble)}")
    qa_run.bold = True
    qa_run.font.size = Pt(9)

    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title_run = title.add_run((draft.title or draft.contract_type or "ДОГОВОР").upper())
    title_run.bold = True
    title_run.font.size = Pt(14)

    date_line = doc.add_paragraph()
    date_line.alignment = WD_ALIGN_PARAGRAPH.CENTER
    date_line.add_run(draft.place_and_date or f"[ТРЕБУЕТ УТОЧНЕНИЯ: место заключения], {_today_kz()}")

    for item in preamble:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        p.paragraph_format.first_line_indent = Cm(0.8)
        p.add_run(item)

    # Numbers exist only here. The draft itself stores headings and clauses
    # without them, so a number can never be rendered twice.
    for number, text, level in iter_numbered_paragraphs(draft.sections):
        p = doc.add_paragraph()
        if level == 0:
            p.alignment = WD_ALIGN_PARAGRAPH.LEFT
            p.paragraph_format.space_before = Pt(10)
            p.add_run(f"{number} {text}").bold = True
            continue
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        p.paragraph_format.first_line_indent = Cm(0.8)
        p.paragraph_format.left_indent = Cm(0.8) if level >= 2 else None
        p.add_run(f"{number} {text}")

    if not draft.sections:
        p = doc.add_paragraph()
        p.add_run("[ТРЕБУЕТ УТОЧНЕНИЯ: существенные и иные условия договора]")

    doc.add_paragraph()
    req_heading = doc.add_paragraph()
    req_heading.add_run("РЕКВИЗИТЫ И ПОДПИСИ СТОРОН").bold = True
    req_heading.alignment = WD_ALIGN_PARAGRAPH.CENTER

    table = doc.add_table(rows=1, cols=2)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.style = "Table Grid"
    left, right = table.rows[0].cells
    left.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.TOP
    right.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.TOP

    left_p = left.paragraphs[0]
    left_p.add_run("Сторона 1\n").bold = True
    for item in (draft.requisites_a or draft.party_a or ["[ТРЕБУЕТ УТОЧНЕНИЯ: реквизиты стороны 1]"]):
        left_p.add_run(f"{item}\n")
    left_p.add_run("\nПодпись: ____________________")

    right_p = right.paragraphs[0]
    right_p.add_run("Сторона 2\n").bold = True
    for item in (draft.requisites_b or draft.party_b or ["[ТРЕБУЕТ УТОЧНЕНИЯ: реквизиты стороны 2]"]):
        right_p.add_run(f"{item}\n")
    right_p.add_run("\nПодпись: ____________________")

    stream = io.BytesIO()
    doc.save(stream)
    return stream.getvalue()
