from __future__ import annotations

import io
from datetime import datetime
from zoneinfo import ZoneInfo

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt
from docx.text.paragraph import Paragraph

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


# Единый источник правды о том, что шаблону реально нужно для сборки документа.
# Раньше такого списка не было нигде, и набор полей, которые спрашивает
# korgan.claim_preflight на входе, невозможно было сверить с тем, что требует
# рендеринг. Названия совпадают с формулировками, которые видит пользователь.
#
# Суд сюда намеренно не входит: точное наименование суда не выводится из закона
# (см. README и production_legal.COURT_PLACEHOLDER), поэтому его отсутствие
# помечается внутри документа, а не блокирует сборку.
REQUIRED_DOCUMENT_FIELDS: tuple[tuple[str, str], ...] = (
    ("claimant", "данные истца (ФИО, ИИН, адрес)"),
    ("defendant", "данные ответчика (ФИО, адрес)"),
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
    """Поля, без которых собирать иск бессмысленно, в понятных пользователю словах.

    Проверка детерминированная и выполняется до рендеринга, чтобы отказ называл
    конкретное недостающее поле вместо generic-сообщения.
    """
    return [
        label
        for attribute, label in REQUIRED_DOCUMENT_FIELDS
        if _is_blank(getattr(draft, attribute, None))
    ]


def _strip_label(value: str, label: str) -> str:
    """Drop a header label the model already put inside the value itself."""
    text = value.strip()
    if text.lower().startswith(label.lower()):
        text = text[len(label):].lstrip(" : \t")
    return text.strip()


def _party_lines(items: list[str], label: str, fallback: str) -> list[str]:
    lines = [_strip_label(item, label) for item in items if item and item.strip()]
    return [line for line in lines if line] or [fallback]


def _restarted_num_id(doc, style_id: str) -> int | None:
    """Clone the style's numbering with startOverride=1."""
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


def _document_status(draft: ClaimDraft) -> str:
    court_text = "\n".join(
        [
            draft.court,
            *draft.claimant,
            *draft.defendant,
            draft.price_of_claim,
            draft.state_duty,
            *draft.facts,
            *draft.legal_basis,
            *draft.requests,
            *draft.attachments,
        ]
    ).upper()

    if (
        "[ТРЕБУЕТ УТОЧНЕНИЯ" in court_text
        or "[ТРЕБУЕТ ДОБАВИТЬ" in court_text
        or NEEDS_CALCULATION_MARKER.upper() in court_text
    ):
        return QA_PRELIMINARY

    if draft.status == VerificationStatus.NEEDS_VERIFICATION or draft.verification_notes:
        return QA_LAWYER_REVIEW

    return QA_READY


def _kazakhstan_today() -> str:
    # Railway runs in UTC; court documents must not roll over a day late.
    return datetime.now(ZoneInfo("Asia/Almaty")).strftime("%d.%m.%Y")


def build_claim_docx(draft: ClaimDraft) -> bytes:
    """Build a clean court-facing DOCX with a visible KORGAN QA readiness status."""
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

    for current_section in doc.sections:
        footer = current_section.footer.paragraphs[0]
        footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = footer.add_run(DRAFT_NOTICE)
        run.font.name = "Times New Roman"
        run.font.size = Pt(8)

    qa = doc.add_paragraph()
    qa.alignment = WD_ALIGN_PARAGRAPH.CENTER
    qa_run = qa.add_run(f"KORGAN QA STATUS: {_document_status(draft)}")
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
    doc.add_paragraph(f"Дата: {_kazakhstan_today()}")
    doc.add_paragraph("Подпись: ____________________")

    stream = io.BytesIO()
    doc.save(stream)
    return stream.getvalue()
