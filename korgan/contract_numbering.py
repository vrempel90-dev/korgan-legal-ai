"""Single source of truth for contract section/clause numbering.

The model supplies contract *structure* (headings, clauses, subclauses); the
numbers themselves are produced only here, at export time. Any literal number
the model still writes into a heading or a clause is stripped before rendering,
so a document can never again show "1. 1. Предмет Договора" or
"3.2. 3.1.1. ...".
"""

from __future__ import annotations

import re

# A leading enumeration such as "1.", "1.1.", "3.1.1)", "Раздел 2.", "п. 4.".
# The separator (dot or bracket) is mandatory, otherwise ordinary text like
# "1 000 000 тенге ..." would be mistaken for a clause number.
_ENUM_PREFIX = re.compile(
    r"^\s*"
    r"(?:(?:раздел|статья|глава|пункт|подпункт)\s+|(?:пп?)\.\s*)?"
    r"(?P<number>[1-9]\d?(?:\.\d{1,2})*)"
    r"\s*[.)]\s+",
    re.IGNORECASE,
)

_MAX_COMPONENTS = 5


def split_leading_number(text: str) -> tuple[int, str]:
    """Split a literal enumeration prefix off ``text``.

    Returns ``(depth, cleaned_text)`` where ``depth`` is the number of numeric
    components of the richest prefix found (``0`` when the text carries no
    number). Already-doubled prefixes ("1.1. 1.1. текст") are peeled off
    completely.
    """
    cleaned = (text or "").strip()
    depth = 0
    while True:
        match = _ENUM_PREFIX.match(cleaned)
        if not match:
            break
        components = match.group("number").split(".")
        if len(components) > _MAX_COMPONENTS:
            break
        rest = cleaned[match.end():].strip()
        if not rest:
            # The whole string is a bare number — keep it rather than emptying
            # the paragraph.
            break
        depth = max(depth, len(components))
        cleaned = rest
    return depth, cleaned


def strip_leading_number(text: str) -> str:
    """Return ``text`` without any literal enumeration prefix."""
    return split_leading_number(text)[1]


def has_leading_number(text: str) -> bool:
    """True when ``text`` starts with a literal enumeration prefix."""
    return split_leading_number(text)[0] > 0


def section_number(section_index: int) -> str:
    return f"{section_index}."


def clause_number(section_index: int, clause_index: int) -> str:
    return f"{section_index}.{clause_index}."


def subclause_number(section_index: int, clause_index: int, sub_index: int) -> str:
    return f"{section_index}.{clause_index}.{sub_index}."


def iter_numbered_paragraphs(sections) -> list[tuple[str, str, int]]:
    """Number a contract body deterministically.

    Yields ``(number, text, level)`` triples where level ``0`` is a section
    heading, ``1`` a clause and ``2`` a subclause. ``sections`` items only have
    to expose ``heading`` and ``clauses``; clauses only ``text`` and
    ``subclauses``.
    """
    numbered: list[tuple[str, str, int]] = []
    for s_index, section in enumerate(sections, start=1):
        numbered.append((section_number(s_index), strip_leading_number(section.heading), 0))
        for c_index, clause in enumerate(section.clauses, start=1):
            numbered.append((clause_number(s_index, c_index), strip_leading_number(clause.text), 1))
            for u_index, sub in enumerate(clause.subclauses, start=1):
                numbered.append((subclause_number(s_index, c_index, u_index), strip_leading_number(sub), 2))
    return numbered


def count_literal_numbers(payload: dict) -> int:
    """Count enumeration prefixes the model wrote into a raw contract payload.

    Used only for observability: the prefixes are stripped on import, but a
    high count means the drafting prompt is being ignored.
    """
    found = 0
    for section in payload.get("sections", []) or []:
        if not isinstance(section, dict):
            continue
        if has_leading_number(str(section.get("heading", ""))):
            found += 1
        for clause in section.get("clauses", []) or []:
            if isinstance(clause, dict):
                if has_leading_number(str(clause.get("text", ""))):
                    found += 1
                found += sum(1 for sub in clause.get("subclauses", []) or [] if has_leading_number(str(sub)))
            elif has_leading_number(str(clause)):
                found += 1
    return found
