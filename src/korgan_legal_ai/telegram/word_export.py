from __future__ import annotations

from io import BytesIO

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Cm, Pt


_MAJOR_HEADINGS = {
    "ИСКОВОЕ ЗАЯВЛЕНИЕ",
    "ОБСТОЯТЕЛЬСТВА ДЕЛА",
    "СВЕДЕНИЯ О ДОСУДЕБНОМ ПОРЯДКЕ",
    "РАСЧЕТ ТРЕБОВАНИЙ",
    "ПРАВОВОЕ ОБОСНОВАНИЕ",
    "ПРОШУ СУД:",
    "ПРИЛОЖЕНИЯ:",
    "ПОДПИСАНТ / ПРЕДСТАВИТЕЛЬ",
}


def _set_run_font(run, *, size: int = 12, bold: bool | None = None, italic: bool = False) -> None:
    run.font.name = "Times New Roman"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "Times New Roman")
    run.font.size = Pt(size)
    if bold is not None:
        run.bold = bold
    run.italic = italic


def build_claim_docx(document_text: str, *, title: str = "Исковое заявление") -> bytes:
    """Build a clean Word file from the already QA-approved document text.

    This function is presentation-only: it does not calculate, rewrite or add legal content.
    NEEDS_VERIFICATION markers are preserved verbatim and emphasized rather than hidden.
    """
    doc = Document()
    section = doc.sections[0]
    section.start_type = WD_SECTION.NEW_PAGE
    section.top_margin = Cm(2)
    section.bottom_margin = Cm(2)
    section.left_margin = Cm(2.5)
    section.right_margin = Cm(1.8)

    normal = doc.styles["Normal"]
    normal.font.name = "Times New Roman"
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), "Times New Roman")
    normal.font.size = Pt(12)
    normal.paragraph_format.space_after = Pt(3)
    normal.paragraph_format.line_spacing = 1.0

    props = doc.core_properties
    props.title = title
    props.subject = "KORGAN Legal AI lawyer-review draft"
    props.author = ""
    props.last_modified_by = ""
    props.comments = "Generated from QA-approved legal draft text."

    lines = document_text.replace("\r\n", "\n").split("\n")
    previous_major = False
    for raw in lines:
        line = raw.rstrip()
        if not line:
            paragraph = doc.add_paragraph()
            paragraph.paragraph_format.space_after = Pt(0)
            previous_major = False
            continue

        stripped = line.strip()
        paragraph = doc.add_paragraph()
        paragraph.paragraph_format.keep_together = False
        paragraph.paragraph_format.keep_with_next = False

        if stripped in _MAJOR_HEADINGS:
            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            paragraph.paragraph_format.space_before = Pt(8)
            paragraph.paragraph_format.space_after = Pt(5)
            paragraph.paragraph_format.keep_with_next = True
            run = paragraph.add_run(stripped)
            _set_run_font(run, size=14 if stripped == "ИСКОВОЕ ЗАЯВЛЕНИЕ" else 12, bold=True)
            previous_major = True
            continue

        if previous_major and stripped.lower().startswith("о "):
            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = paragraph.add_run(stripped)
            _set_run_font(run, size=12, bold=False)
            previous_major = False
            continue

        if stripped.startswith("NEEDS_VERIFICATION") or "NEEDS_VERIFICATION —" in stripped:
            run = paragraph.add_run(stripped)
            _set_run_font(run, bold=True)
            previous_major = False
            continue

        if stripped.startswith("ЦЕНА ИСКА:"):
            run = paragraph.add_run(stripped)
            _set_run_font(run, bold=True)
            previous_major = False
            continue

        if stripped.startswith(("Истец:", "Ответчик:", "БИН/ИИН:", "Адрес:")):
            run = paragraph.add_run(stripped)
            _set_run_font(run)
            previous_major = False
            continue

        run = paragraph.add_run(stripped)
        _set_run_font(run)
        previous_major = False

    output = BytesIO()
    doc.save(output)
    return output.getvalue()
