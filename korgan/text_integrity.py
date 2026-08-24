"""Detect text that was cut, glued or contaminated between pipeline steps.

These are shape checks on finished client-facing legal text. A finding means the
text is damaged or contains an internal serialization artefact and must not be
released as a clean legal document.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_LOWER = "а-яёa-z"
_UPPER = "А-ЯЁA-Z"

_PATTERNS: tuple[tuple[str, str, str], ...] = (
    (
        "closing_quote_glued",
        rf"[»”][.,;:]?[{_LOWER}{_UPPER}]",
        "к закрывающей кавычке приклеено слово без пробела (например «».евидно»)",
    ),
    (
        "sentence_glued",
        rf"[{_LOWER}]{{3,}}\.[{_LOWER}{_UPPER}]{{2}}",
        "точка между словами без пробела — склейка двух фрагментов текста",
    ),
    (
        "opening_quote_glued",
        rf"[{_LOWER}{_UPPER}]«",
        "открывающая кавычка приклеена к предыдущему слову",
    ),
    (
        "repeated_punctuation",
        r",{2,}|;{2,}|:{2,}|,\.",
        "повторяющаяся пунктуация — след склейки фрагментов",
    ),
    (
        "space_before_punctuation",
        r"\s+[,;:]",
        "пробел перед знаком препинания",
    ),
    (
        "internal_serialization_field",
        r"(?i)\b(?:claim_amount|case_amount|case_context|document_type|text_summary|"
        r"verification_notes|source_urls|missing_or_unclear|important_facts|extracted_document)\b",
        "в юридический текст попало внутреннее техническое поле",
    ),
    (
        "glued_currency_index",
        r"(?i)\b(?:тенге|теңге|тг)\d{1,3}\b",
        "к обозначению валюты приклеен технический индекс/номер",
    ),
    (
        "unresolved_alt_placeholder",
        r"(?i)\[(?:НУЖНО\s+ДОПОЛНИТЬ|НУЖНО\s+УТОЧНИТЬ|ДОПОЛНИТЬ|УТОЧНИТЬ)\s*:[^\]]+\]",
        "в документе осталось незаполненное служебное поле",
    ),
)

_ALLOWED = re.compile(
    r"|".join(
        (
            r"\b(?:т\.е|т\.к|т\.д|т\.п|и\.о|см\.|стр\.|гл\.|ст\.|п\.п|пп\.|руб\.|тг\.)",
            r"\b[А-ЯЁ]\.\s?[А-ЯЁ]\.",
            r"\b(?:kz|ru|com|org|net|gov)\b",
            r"\d+\.\d+",
            r"https?://\S+",
            r"\w+\.(?:kz|ru|com|org|net)\b",
        )
    ),
    re.IGNORECASE,
)


@dataclass(slots=True)
class IntegrityFinding:
    code: str
    description: str
    excerpt: str

    def as_note(self) -> str:
        return f"{self.description}: «{self.excerpt}»"


def _mask_allowed(text: str) -> str:
    """Mask legitimate spans while preserving offsets."""
    return _ALLOWED.sub(lambda match: "_" * len(match.group(0)), text)


def unbalanced_quotes(text: str) -> bool:
    return text.count("«") != text.count("»")


def integrity_findings(text: str) -> list[IntegrityFinding]:
    """Return every structural damage or internal artefact found in ``text``."""
    if not text:
        return []

    masked = _mask_allowed(text)
    findings: list[IntegrityFinding] = []

    for code, pattern, description in _PATTERNS:
        flags = re.IGNORECASE if pattern.startswith("(?i)") else 0
        effective_pattern = pattern[4:] if pattern.startswith("(?i)") else pattern
        for match in re.finditer(effective_pattern, masked, flags=flags):
            start = max(0, match.start() - 40)
            end = min(len(text), match.end() + 40)
            excerpt = " ".join(text[start:end].split())
            findings.append(IntegrityFinding(code, description, excerpt))

    if unbalanced_quotes(text):
        findings.append(
            IntegrityFinding(
                "unbalanced_quotes",
                "непарные кавычки — цитата оборвана",
                f"«: {text.count('«')}, »: {text.count('»')}",
            )
        )

    return findings


def is_intact(text: str) -> bool:
    return not integrity_findings(text)
