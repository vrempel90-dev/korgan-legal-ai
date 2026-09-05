"""Presentation-only cleanup at delivery; legal release decisions stay intact."""

from __future__ import annotations

import io
import re

from docx import Document
from docx.oxml.ns import qn


_INTERNAL_PARAGRAPH = re.compile(
    r"^(?:KORGAN\s+(?:QA\s+STATUS|QUALITY)\b|"
    r"(?:verification_notes|quality_issues|provider_status|SENIOR_PREFLIGHT|FILING_ACTION)\s*[:=]|"
    r"(?:PRELIMINARY DRAFT|LAWYER-REVIEW DRAFT|READY FOR FINAL HUMAN REVIEW|NEEDS_VERIFICATION)\s*$)",
    re.IGNORECASE,
)
_GENERATOR_FOOTERS = (
    "Проект сформирован KORGAN Legal AI на основании материалов пользователя.",
    "Проект сформирован KORGAN Legal AI на основании материалов пользователя и проверенных правовых источников.",
    "Жоба KORGAN Legal AI арқылы пайдаланушы материалдарының негізінде қалыптастырылды.",
)


def clean_client_docx(data: bytes) -> bytes:
    """Remove standalone machine labels from every Word story, preserving runs.

    Keep legal text, citations and missing-fact placeholders. Release gates see
    the original draft and metadata before this output-only transformation.
    An untouched file is returned byte-for-byte, including legacy test payloads.
    """
    try:
        document = Document(io.BytesIO(data))
    except Exception:
        return data

    changed = False
    for part in document.part.package.parts:
        root = getattr(part, "element", None)
        if root is None:
            continue
        # Includes body tables, nested cells, text boxes, headers and footers.
        for paragraph in list(root.iter(qn("w:p"))):
            text = "".join(
                node.text or "" for node in paragraph.iter(qn("w:t"))
            ).strip()
            if not (_INTERNAL_PARAGRAPH.match(text) or text.startswith(_GENERATOR_FOOTERS)):
                continue
            parent = paragraph.getparent()
            if parent is None:
                continue
            # Word requires a terminating paragraph in a table cell/story.
            if parent.tag == qn("w:tc") or len(parent.findall(qn("w:p"))) == 1:
                for child in list(paragraph):
                    if child.tag != qn("w:pPr"):
                        paragraph.remove(child)
            else:
                parent.remove(paragraph)
            changed = True

    if not changed:
        return data
    output = io.BytesIO()
    document.save(output)
    return output.getvalue()
