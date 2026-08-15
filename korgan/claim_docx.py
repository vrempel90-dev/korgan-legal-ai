from __future__ import annotations

import io
from datetime import date

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt
from docx.text.paragraph import Paragraph

from korgan.legal_calc import NEEDS_CALCULATION_MARKER
from korgan.legal_types import ClaimDraft


DRAFT_NOTICE = (
    "Проект сформирован KORGAN Legal AI на основании материалов пользователя. "
    "Перед подачей необходимо проверить реквизиты, доказательства, подсудность, госпошлину и отмеченные системой вопросы. "
    "Формирование проекта не гарантирует принятие документа или исход дела."
)


def _strip_label(value: str, label: str) -> str:
    """Drop a header label the model already put inside the value itself.

    The template prints «Истец:» once; when the draft field also starts with it,
    the header renders «Истец: Истец: Иванов И.И.» — a QA section H failure.
    """
    text = value.strip()
    if text.lower().startswith(label.lower()):
        text = text[len(label):].lstrip(" : \t")
    return text.strip()


def _party_lines(items: list[str], label: str, fallback: str) -> list[str]:
    lines = [_strip_label(item, label) for item in items if item and item.strip()]
    return [line for line in lines if line] or [fallback]


def _restarted_num_id(doc, style_id: str) -> int | None:
    """Clone the style's numbering with startOverride=1.

    Every «List Number» paragraph shares one numId, so the annex list would
    otherwise continue the prayer-for-relief numbering instead of starting at 1.
    """
    style_num_id = None
    for style in doc.styles.element.findall(qn("w:style")):
        if style.get(qn("w:styleId")) != style_id:
            continue
        found = style.find(f'{qn("w:pPr")}/{qn("w:numPr")}/{qn("w:numId")}')
        if found is not None:
            style_num_id = found.get(qn("w:val"))
        break

    if style_num_id is None:
        return None

    numbering = doc.part.numbering_part.element
    abstract_id = None
    used_ids = set()
    for num in numbering.findall(qn("w:num")):
        current = num.get(qn("w:numId"))
        if current is not None and current.isdigit():
            used_ids.add(int(current))
        if current == style_num_id:
            reference = num.find(qn("w:abstractNumId"))
            if reference is not None:
                abstract_id = reference.get(qn("w:val"))

    if abstract_id is None:
        return None

    new_id = max(used_ids, default=0) + 1
    num = OxmlElement("w:num")
    num.set(qn("w:numId"), str(new_id))
    reference = OxmlElement("w:abstractNumId")
    reference.set(qn("w:val"), abstract_id)
    num.append(reference)
    override = OxmlElement("w:lvlOverride")
    override.set(qn("w:ilvl"), "0")
    start_override = OxmlElement("w:startOverride")
    start_override.set(qn("w:val"), "1")
    override.append(start_override)
    num.append(override)
    numbering.append(num)
    return new_id


def _apply_num_id(paragraph: Paragraph, num_id: int) -> None:
    num_pr = paragraph._p.get_or_add_pPr().get_or_add_numPr()
    num_pr.get_or_add_ilvl().val = 0
    num_pr.get_or_add_numId().val = num_id


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
    # Never absent: either a computed amount or the explicit calculation marker.
    duty = _strip_label(draft.state_duty, "Госпошлина") or NEEDS_CALCULATION_MARKER
    right.add_run(f"Госпошлина: {duty}")

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
    annex_num_id = _restarted_num_id(doc, "ListNumber")
    for attachment in draft.attachments:
        paragraph = doc.add_paragraph(attachment, style="List Number")
        if annex_num_id is not None:
            _apply_num_id(paragraph, annex_num_id)

    doc.add_paragraph()
    doc.add_paragraph(f"Дата: {date.today().strftime('%d.%m.%Y')}")
    doc.add_paragraph("Подпись: ____________________")

    stream = io.BytesIO()
    doc.save(stream)
    return stream.getvalue()
