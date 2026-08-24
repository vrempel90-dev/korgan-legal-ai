from __future__ import annotations

import re

from korgan.legal_types import ClaimDraft


_INTERNAL_FIELD_RE = re.compile(
    r"(?i)\b(?:claim_amount|case_amount|case_context|document_type|text_summary|"
    r"verification_notes|source_urls|missing_or_unclear|important_facts|extracted_document)\b\s*[:=]?\s*"
)
_SOURCE_MARKER_RE = re.compile(
    r"(?i)^\s*(?:ТРЕБОВАНИЕ\s+ИЗ\s+ДОКУМЕНТА|ФАКТ\s+ИЗ\s+ДОКУМЕНТА|"
    r"ИЗВЛЕЧЕНО\s+ИЗ\s+ДОКУМЕНТА)\s*:\s*"
)
_LEADING_LIST_RE = re.compile(r"^\s*\d{1,3}[.)]\s+")
_GLUED_CURRENCY_INDEX_RE = re.compile(r"(?i)\b(тенге|теңге|тг)(\d{1,3})\b")
_MULTI_SPACE_RE = re.compile(r"[ \t]{2,}")
_META_ATTACHMENT_RE = re.compile(
    r"(?i)^\s*(?:"
    r"уточнение\s+к\s+ранее\s+описанному\s+юридическому\s+документу|"
    r"уточнение\s+к\s+ранее\s+загруженному\s+документу|"
    r"дополнительный\s+контекст\s+к\s+документу|"
    r"техническое\s+уточнение\s+к\s+документу"
    r")"
)


def _clean_line(raw: str) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    text = _SOURCE_MARKER_RE.sub("", text)
    text = _LEADING_LIST_RE.sub("", text)
    text = _INTERNAL_FIELD_RE.sub("", text)
    text = _GLUED_CURRENCY_INDEX_RE.sub(r"\1", text)
    text = _MULTI_SPACE_RE.sub(" ", text)
    text = re.sub(r"\s+([,;:.])", r"\1", text)
    text = re.sub(r"([,;:])\s*[,;:]+", r"\1", text)
    return text.strip(" \t;,")


def _clean_list(values: list[str], *, attachments: bool = False) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in values or []:
        original = str(raw or "").strip()
        if attachments and _META_ATTACHMENT_RE.search(original):
            continue
        text = _clean_line(original)
        if not text:
            continue
        key = re.sub(r"\W+", "", text.casefold())
        if key and key not in seen:
            seen.add(key)
            result.append(text)
    return result


def sanitize_claim_filing_text(draft: ClaimDraft) -> None:
    """Remove serialization/intake artefacts without changing legal substance."""
    draft.title = _clean_line(draft.title)
    draft.court = _clean_line(draft.court)
    draft.claimant = _clean_list(draft.claimant)
    draft.defendant = _clean_list(draft.defendant)
    draft.facts = _clean_list(draft.facts)
    draft.legal_basis = _clean_list(draft.legal_basis)
    draft.requests = _clean_list(draft.requests)
    draft.attachments = _clean_list(draft.attachments, attachments=True)
    draft.verification_notes = _clean_list(draft.verification_notes)
