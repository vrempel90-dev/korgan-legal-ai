from __future__ import annotations

import re
import secrets
from datetime import datetime, timezone
from typing import Any

_CASE_REF_RE = re.compile(r"^KRG-\d{6}-[A-F0-9]{6}$")
_CASE_REF_IN_FILENAME_RE = re.compile(r"(?i)(KRG-\d{6}-[A-F0-9]{6})")

_DOC_KIND_LABELS = {
    "claim": {"ru": "Исковое заявление", "kk": "Талап қою арызы"},
    "pretrial": {"ru": "Досудебная претензия", "kk": "Сотқа дейінгі талап"},
    "response": {"ru": "Отзыв на иск", "kk": "Талап қоюға пікір"},
    "contract": {"ru": "Договор", "kk": "Шарт"},
    "document": {"ru": "Юридический документ", "kk": "Заң құжаты"},
}


def new_case_reference() -> str:
    """Create a short non-PII reference suitable for client-facing messages."""
    date_part = datetime.now(timezone.utc).strftime("%y%m%d")
    random_part = secrets.token_hex(3).upper()
    return f"KRG-{date_part}-{random_part}"


def valid_case_reference(value: str | None) -> bool:
    return bool(value and _CASE_REF_RE.fullmatch(str(value).strip().upper()))


async def ensure_case_reference(state: Any) -> str:
    """Return the current KORGAN case reference, creating it once per case state."""
    data = await state.get_data()
    existing = str(data.get("case_reference", "") or "").strip().upper()
    if valid_case_reference(existing):
        return existing

    reference = new_case_reference()
    await state.update_data(case_reference=reference)
    return reference


def filename_with_case_reference(filename: str, case_reference: str) -> str:
    """Embed the safe case reference without changing KORGAN document detection."""
    name = str(filename or "KORGAN_document.docx")
    reference = str(case_reference or "").strip().upper()
    if not valid_case_reference(reference) or _CASE_REF_IN_FILENAME_RE.search(name):
        return name
    if name.lower().startswith("korgan_"):
        return f"KORGAN_{reference}_{name[len('KORGAN_'):]}"
    return f"KORGAN_{reference}_{name}"


def case_reference_from_filename(filename: str | None) -> str | None:
    match = _CASE_REF_IN_FILENAME_RE.search(str(filename or ""))
    return match.group(1).upper() if match else None


def document_kind_from_filename(filename: str | None) -> str:
    name = str(filename or "").lower()
    if "otzyv" in name or "response" in name:
        return "response"
    if "dosudeb" in name or "sotqa_deyingi" in name or "pretrial" in name:
        return "pretrial"
    if "dogovor" in name or "contract" in name:
        return "contract"
    if "iskov" in name or "claim" in name:
        return "claim"
    return "document"


def document_label(kind: str, language: str = "ru") -> str:
    normalized_kind = kind if kind in _DOC_KIND_LABELS else "document"
    lang = "kk" if str(language).lower() == "kk" else "ru"
    return _DOC_KIND_LABELS[normalized_kind][lang]


def consultation_callback_data(case_reference: str, document_kind: str) -> str:
    reference = str(case_reference or "").strip().upper()
    kind = document_kind if document_kind in _DOC_KIND_LABELS else "document"
    if not valid_case_reference(reference):
        raise ValueError("invalid KORGAN case reference")
    value = f"lawyer:request:{reference}:{kind}"
    if len(value.encode("utf-8")) > 64:
        raise ValueError("Telegram callback_data limit exceeded")
    return value
