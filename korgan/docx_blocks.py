"""The one place in KORGAN that is allowed to put a number on a paragraph.

Every document type — claim, contract, response to a claim — is described as a
flat list of typed blocks and rendered through :func:`render_blocks`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt
from docx.text.paragraph import Paragraph

from korgan.contract_numbering import strip_leading_number


@dataclass(slots=True)
class Heading:
    text: str
    centered: bool = False
    space_before: int = 10


@dataclass(slots=True)
class Prose:
    text: str
    indent_levels: int = 0
    first_line_indent: bool = True
    centered: bool = False
    bold: bool = False


@dataclass(slots=True)
class NumberedItem:
    text: str
    level: int = 0
    bold: bool = False


@dataclass(slots=True)
class AutoNumberedList:
    """A numbered list.

    ``restart=True`` is used for independent legal-document sections such as
    «Приложения». Those sections are rendered with deterministic visible
    numbers starting at 1 instead of relying on Word's inherited list state.
    This prevents a request list ending at 4 from making attachments start at 5.
    """

    items: list[str] = field(default_factory=list)
    restart: bool = False


@dataclass(slots=True)
class Spacer:
    pass


Block = Heading | Prose | NumberedItem | AutoNumberedList | Spacer


def advance(counters: list[int], level: int) -> str:
    if level < 0:
        raise ValueError("numbering level must not be negative")
    while len(counters) <= level:
        counters.append(0)
    del counters[level + 1:]
    counters[level] += 1
    return ".".join(str(value) for value in counters[: level + 1]) + "."


def _restarted_num_id(doc, style_id: str) -> int | None:
    """Legacy Word-list restart helper kept for non-critical compatibility."""
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


def _render_forced_restart(doc, items: list[str]) -> None:
    """Render an independent list with literal 1..N numbering.

    Word list styles can inherit the previous ``numId`` depending on the viewer
    and template. Court documents need deterministic visible numbering, so an
    explicitly restarted section does not depend on that mutable Word state.
    """
    for index, item in enumerate(items, start=1):
        paragraph = doc.add_paragraph()
        paragraph.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        paragraph.paragraph_format.left_indent = Cm(0.8)
        paragraph.paragraph_format.first_line_indent = Cm(-0.8)
        paragraph.add_run(f"{index}. {strip_leading_number(item)}")


def render_blocks(doc, blocks: list[Block]) -> None:
    counters: list[int] = []

    for block in blocks:
        if isinstance(block, Spacer):
            doc.add_paragraph()
            continue

        if isinstance(block, Heading):
            paragraph = doc.add_paragraph()
            paragraph.alignment = (
                WD_ALIGN_PARAGRAPH.CENTER if block.centered else WD_ALIGN_PARAGRAPH.LEFT
            )
            paragraph.paragraph_format.space_before = Pt(block.space_before)
            paragraph.add_run(block.text).bold = True
            continue

        if isinstance(block, Prose):
            paragraph = doc.add_paragraph()
            paragraph.alignment = (
                WD_ALIGN_PARAGRAPH.CENTER if block.centered else WD_ALIGN_PARAGRAPH.JUSTIFY
            )
            if block.first_line_indent:
                paragraph.paragraph_format.first_line_indent = Cm(0.8)
            if block.indent_levels:
                paragraph.paragraph_format.left_indent = Cm(0.8 * block.indent_levels)
            paragraph.add_run(block.text).bold = block.bold
            continue

        if isinstance(block, NumberedItem):
            number = advance(counters, block.level)
            paragraph = doc.add_paragraph()
            if block.level == 0 and block.bold:
                paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
                paragraph.paragraph_format.space_before = Pt(10)
            else:
                paragraph.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
                paragraph.paragraph_format.first_line_indent = Cm(0.8)
                if block.level >= 2:
                    paragraph.paragraph_format.left_indent = Cm(0.8)
            run = paragraph.add_run(f"{number} {strip_leading_number(block.text)}")
            run.bold = block.bold
            continue

        if isinstance(block, AutoNumberedList):
            if block.restart:
                _render_forced_restart(doc, block.items)
                continue
            for item in block.items:
                doc.add_paragraph(strip_leading_number(item), style="List Number")
            continue

        raise TypeError(f"unsupported document block: {type(block).__name__}")
