from __future__ import annotations

import re

from korgan.claim_preflight import (
    ClaimPreflight,
    _CLAIMANT_MARKERS,
    _DEFENDANT_MARKERS,
    _LEGAL_ENTITY_MARKERS,
    _has_claimant_dob,
    _has_role_bound_iin,
    _has_role_bound_name,
    _windows,
)

_ADDRESS_SIGNAL = (
    "адрес",
    "место жительства",
    "место нахождения",
    "проживает",
    "проживаю",
    "живу ",
    "живет",
    "живёт",
    "ул.",
    " улица ",
    "дом ",
    "д. ",
    "квартира",
    "кв.",
    "мкр",
    "проспект",
)


def _segments(text: str) -> list[str]:
    # Extracted contexts commonly separate party-bound values with semicolons;
    # user narratives more often use new lines or sentences.
    return [part.strip() for part in re.split(r"[;\n]+", text) if part.strip()]


def _looks_like_address(segment: str) -> bool:
    lowered = f" {segment.lower()} "
    return any(token in lowered for token in _ADDRESS_SIGNAL)


def _has_strict_party_address(text: str, party: str) -> bool:
    markers = _CLAIMANT_MARKERS if party == "claimant" else _DEFENDANT_MARKERS

    # Strongest signal: the same short field/segment explicitly names the party
    # and carries an address/residence marker. This prevents a nearby defendant
    # address from satisfying the claimant requirement.
    for segment in _segments(text):
        lowered = segment.lower()
        if any(marker in lowered for marker in markers) and _looks_like_address(segment):
            return True

    lowered = text.lower()
    if party == "claimant":
        first_person_patterns = (
            r"\bмой\s+адрес\b",
            r"\bадрес\s+истц[а-яё]*\b",
            r"\bместо\s+жительства\s+истц[а-яё]*\b",
            r"\bя\s+проживаю\b",
            r"\bя\s+живу\b",
            r"\bпроживаю\s+по\s+адресу\b",
        )
        return any(re.search(pattern, lowered) for pattern in first_person_patterns)

    defendant_patterns = (
        r"\bадрес\s+ответчик[а-яё]*\b",
        r"\bместо\s+жительства\s+ответчик[а-яё]*\b",
        r"\bответчик[а-яё]*.{0,80}\b(?:живет|живёт|проживает)\b",
        r"\bон\s+(?:живет|живёт|проживает)\b",
    )
    return any(re.search(pattern, lowered, flags=re.DOTALL) for pattern in defendant_patterns)


def inspect_claim_context(case_context: str) -> ClaimPreflight:
    text = case_context.strip()
    if not text:
        return ClaimPreflight(("описание обстоятельств дела или материалы",))

    claimant_windows = "\n".join(_windows(text, _CLAIMANT_MARKERS, 260)).lower()
    claimant_is_legal_entity = any(marker in claimant_windows for marker in _LEGAL_ENTITY_MARKERS)

    missing: list[str] = []

    if claimant_is_legal_entity:
        if not _has_role_bound_name(text, _CLAIMANT_MARKERS):
            missing.append("полное наименование истца")
        if not _has_role_bound_iin(text, _CLAIMANT_MARKERS):
            missing.append("БИН истца")
        if not _has_strict_party_address(text, "claimant"):
            missing.append("место нахождения истца")
        if "банковск" not in claimant_windows and "iban" not in claimant_windows:
            missing.append("банковские реквизиты истца")
    else:
        if not _has_role_bound_name(text, _CLAIMANT_MARKERS):
            missing.append("ФИО истца полностью")
        if not _has_claimant_dob(text):
            missing.append("дата рождения истца")
        if not _has_role_bound_iin(text, _CLAIMANT_MARKERS):
            missing.append("ИИН истца")
        if not _has_strict_party_address(text, "claimant"):
            missing.append("адрес места жительства истца")

    if not _has_role_bound_name(text, _DEFENDANT_MARKERS):
        missing.append("ФИО ответчика полностью")
    if not _has_strict_party_address(text, "defendant"):
        missing.append("адрес места жительства ответчика")

    return ClaimPreflight(tuple(dict.fromkeys(missing)))
