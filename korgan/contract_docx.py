from __future__ import annotations

import io
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Cm, Pt

from korgan.contract_preamble import ensure_identified_preamble
from korgan.docx_blocks import Block, Heading, NumberedItem, Prose, render_blocks
from korgan.legal_types import ContractDraft, VerificationStatus


DRAFT_NOTICE = (
    "Проект сформирован KORGAN Legal AI на основании материалов пользователя и проверенных правовых источников. "
    "Перед подписанием необходимо проверить реквизиты сторон, коммерческие условия и отмеченные системой вопросы."
)

_REQUISITES_SECTION_RE = re.compile(
    r"(?i)^\s*(?:"
    r"реквизит\w*(?:\s+и\s+подпис\w*)?(?:\s+сторон)?|"
    r"адрес\w*\s+и\s+реквизит\w*(?:\s+сторон)?|"
    r"подпис\w*\s+сторон|"
    r"местонахождени\w*\s+и\s+(?:банковск\w*\s+)?реквизит\w*"
    r")\s*[.:;-]*\s*$"
)
_SIGNATURE_LINE_RE = re.compile(
    r"(?i)^\s*(?:подпис\w*|signature|м\.?\s*п\.?)\s*[:_\-–—.\s]*$"
)
_PARTY_LABEL_RE = re.compile(r"(?i)^\s*(?:сторона\s*[12аб]|party\s*[ab12])\s*:?[\s.]*$")


def _status(draft: ContractDraft, preamble: list[str]) -> str:
    body = "\n".join([*draft.body_lines(), *preamble]).upper()
    if "[ТРЕБУЕТ УТОЧНЕНИЯ" in body:
        return "PRELIMINARY DRAFT"
    if draft.status == VerificationStatus.NEEDS_VERIFICATION or draft.verification_notes:
        return "LAWYER-REVIEW DRAFT"
    return "READY FOR FINAL HUMAN REVIEW"


def _today_kz() -> str:
    return datetime.now(ZoneInfo("Asia/Almaty")).strftime("%d.%m.%Y")


def _renderer_owned_requisites_section(heading: str) -> bool:
    """The DOCX renderer owns the single final requisites/signature block."""
    return bool(_REQUISITES_SECTION_RE.fullmatch(" ".join(str(heading or "").split())))


def _clean_requisites(values: list[str], fallback: list[str]) -> list[str]:
    result: list[str] = []
    for raw in values or fallback:
        value = " ".join(str(raw or "").split()).strip()
        if not value or _SIGNATURE_LINE_RE.fullmatch(value) or _PARTY_LABEL_RE.fullmatch(value):
            continue
        key = re.sub(r"\W+", "", value.casefold())
        if key and not any(re.sub(r"\W+", "", item.casefold()) == key for item in result):
            result.append(value)
    return result


def _body_blocks(draft: ContractDraft, preamble: list[str]) -> list[Block]:
    """Describe the contract body; numbering is left entirely to the renderer."""
    blocks: list[Block] = [Prose(item) for item in preamble]

    for section in draft.sections:
        # The model occasionally emits a normal numbered section called
        # «Реквизиты и подписи сторон». Rendering it and then appending the
        # canonical two-column signature table produces duplicate signatures.
        # Skip only dedicated requisites sections; combined substantive sections
        # such as «Заключительные положения и реквизиты» remain untouched.
        if _renderer_owned_requisites_section(section.heading):
            continue
        blocks.append(NumberedItem(section.heading, level=0, bold=True))
        for clause in section.clauses:
            blocks.append(NumberedItem(clause.text, level=1))
            blocks.extend(NumberedItem(sub, level=2) for sub in clause.subclauses)

    if not draft.sections:
        blocks.append(
            Heading("[ТРЕБУЕТ УТОЧНЕНИЯ: существенные и иные условия договора]")
        )
    return blocks


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

    # The identification block is mandatory: when the model omitted it, the
    # export inserts the structure with visible gaps instead of shipping a
    # contract whose parties are only named in the requisites table.
    preamble = ensure_identified_preamble(
        draft.preamble,
        party_a=draft.party_a,
        party_b=draft.party_b,
    )
    document_status = _status(draft, preamble)

    # Internal product QA is useful only on a non-ready project. A contract that
    # passed the universal quality bar must be a clean signing document.
    if document_status != "READY FOR FINAL HUMAN REVIEW":
        footer = section.footer.paragraphs[0]
        footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = footer.add_run(DRAFT_NOTICE)
        run.font.name = "Times New Roman"
        run.font.size = Pt(8)

        qa = doc.add_paragraph()
        qa.alignment = WD_ALIGN_PARAGRAPH.CENTER
        qa_run = qa.add_run(f"KORGAN QA STATUS: {document_status}")
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

    render_blocks(doc, _body_blocks(draft, preamble))

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

    left_values = _clean_requisites(
        draft.requisites_a,
        draft.party_a or ["[ТРЕБУЕТ УТОЧНЕНИЯ: реквизиты стороны 1]"],
    ) or ["[ТРЕБУЕТ УТОЧНЕНИЯ: реквизиты стороны 1]"]
    right_values = _clean_requisites(
        draft.requisites_b,
        draft.party_b or ["[ТРЕБУЕТ УТОЧНЕНИЯ: реквизиты стороны 2]"],
    ) or ["[ТРЕБУЕТ УТОЧНЕНИЯ: реквизиты стороны 2]"]

    left_p = left.paragraphs[0]
    left_p.add_run("Сторона 1\n").bold = True
    for item in left_values:
        left_p.add_run(f"{item}\n")
    left_p.add_run("\nПодпись: ____________________")

    right_p = right.paragraphs[0]
    right_p.add_run("Сторона 2\n").bold = True
    for item in right_values:
        right_p.add_run(f"{item}\n")
    right_p.add_run("\nПодпись: ____________________")

    stream = io.BytesIO()
    doc.save(stream)
    return stream.getvalue()
