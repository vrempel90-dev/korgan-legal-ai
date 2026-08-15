from __future__ import annotations

import io
from datetime import datetime
from zoneinfo import ZoneInfo

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Cm, Pt

from korgan.legal_types import ContractDraft, VerificationStatus


DRAFT_NOTICE = (
    "Проект сформирован KORGAN Legal AI на основании материалов пользователя и проверенных правовых источников. "
    "Перед подписанием необходимо проверить реквизиты сторон, коммерческие условия и отмеченные системой вопросы."
)


def _status(draft: ContractDraft) -> str:
    body = "\n".join(
        [
            draft.title,
            draft.place_and_date,
            *draft.party_a,
            *draft.party_b,
            *draft.preamble,
            *(clause for section in draft.sections for clause in section.clauses),
            *draft.requisites_a,
            *draft.requisites_b,
        ]
    ).upper()
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

    qa = doc.add_paragraph()
    qa.alignment = WD_ALIGN_PARAGRAPH.CENTER
    qa_run = qa.add_run(f"KORGAN QA STATUS: {_status(draft)}")
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

    for item in draft.preamble:
        p = doc.add_paragraph(item)
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY

    if not draft.preamble:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        p.add_run(
            "[ТРЕБУЕТ УТОЧНЕНИЯ: сведения о сторонах и лицах, подписывающих договор, а также основания их полномочий]"
        )

    for section_index, contract_section in enumerate(draft.sections, start=1):
        heading = doc.add_paragraph()
        heading.alignment = WD_ALIGN_PARAGRAPH.LEFT
        heading_run = heading.add_run(f"{section_index}. {contract_section.heading}")
        heading_run.bold = True

        for clause_index, clause in enumerate(contract_section.clauses, start=1):
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
            p.paragraph_format.first_line_indent = Cm(0.8)
            p.add_run(f"{section_index}.{clause_index}. {clause}")

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
