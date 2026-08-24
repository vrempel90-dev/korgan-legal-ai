from __future__ import annotations

import re
from dataclasses import dataclass


_BIN_RE = re.compile(r"\bБИН\s*[:\-–]?\s*(\d{12})\b", re.IGNORECASE)
_IIN_RE = re.compile(r"\bИИН\s*[:\-–]?\s*(\d{12})\b", re.IGNORECASE)
_LEGAL_FORM_RE = re.compile(
    r"(?i)(?:\bТОО\b|\bАО\b|товариществ\w*\s+с\s+ограниченн\w*\s+ответственност\w*|акционерн\w*\s+обществ\w*)"
)
_IP_RE = re.compile(r"(?i)(?:\bИП\b|индивидуальн\w*\s+предпринимател\w*)")
_QUOTED_RE = re.compile(r"[«\"]([^»\"]{3,120})[»\"]")
_PERSON_RE = re.compile(
    r"\b[А-ЯЁA-Z][а-яёa-z-]{1,40}\s+[А-ЯЁA-Z][а-яёa-z-]{1,40}(?:\s+[А-ЯЁA-Z][а-яёa-z-]{1,40})?\b"
)
_ROLE_PREFIX_RE = re.compile(
    r"(?i)^\s*(?:истец|заявитель|поставщик|заказчик|исполнитель|подрядчик|арендодатель|арендатор|"
    r"продавец|покупатель|кредитор|займодавец|заимодавец|работодатель|работник|сторона\s*\d*)\s*:\s*"
)
_TOKEN_RE = re.compile(r"[0-9A-Za-zА-Яа-яЁё]{4,}")
_STOPWORDS = {
    "истец", "заявитель", "адрес", "город", "улица", "район", "область", "республика",
    "казахстан", "телефон", "email", "банковские", "реквизиты", "поставщик", "заказчик",
    "исполнитель", "подрядчик", "арендодатель", "арендатор", "продавец", "покупатель",
    "кредитор", "займодавец", "заимодавец", "работодатель", "работник", "товарищество",
    "ограниченной", "ответственностью", "акционерное", "общество", "company", "group",
    "holding", "services", "service", "solutions", "international", "corporation",
}


@dataclass(frozen=True, slots=True)
class PartyIdentityMatch:
    kind: str
    identifier_label: str
    identifier: str
    source_fragment: str


def _normalized(value: str) -> str:
    return "".join(ch.lower() for ch in str(value or "").replace("ё", "е") if ch.isalnum())


def _clear_party_type(values: list[str]) -> str | None:
    text = "\n".join(str(item or "") for item in values or [])
    if _BIN_RE.search(text) or _LEGAL_FORM_RE.search(text):
        return "legal_entity"
    if _IIN_RE.search(text) or _IP_RE.search(text):
        return "individual"
    return None


def _distinctive_tokens(text: str) -> list[str]:
    return [
        token
        for token in _TOKEN_RE.findall(text or "")
        if token.lower().replace("ё", "е") not in _STOPWORDS and not token.isdigit()
    ]


def _identity_keys(values: list[str]) -> list[str]:
    text = " ".join(str(item or "") for item in values or [])
    strong: list[str] = []

    for quoted in _QUOTED_RE.findall(text):
        key = _normalized(quoted)
        if len(key) >= 5 and key not in strong:
            strong.append(key)

    for match in _PERSON_RE.finditer(text):
        key = _normalized(match.group(0))
        if len(key) >= 8 and key not in strong:
            strong.append(key)

    # Build a phrase key from adjacent distinctive name tokens. This prevents a
    # claimant such as "ABC GROUP" from accidentally matching the defendant
    # "CLIENT GROUP" merely because both contain the generic word GROUP.
    for raw in values or []:
        tokens = _distinctive_tokens(_ROLE_PREFIX_RE.sub("", str(raw or "")))
        if len(tokens) >= 2:
            key = _normalized(" ".join(tokens[:4]))
            if len(key) >= 8 and key not in strong:
                strong.append(key)
        elif len(tokens) == 1:
            token = tokens[0]
            if len(token) >= 7:
                key = _normalized(token)
                if key not in strong:
                    strong.append(key)

    if strong:
        return strong

    tokens = _distinctive_tokens(text)
    tokens.sort(key=len, reverse=True)
    return [
        key
        for key in (_normalized(token) for token in tokens[:4])
        if len(key) >= 7
    ]


def _windows(case_context: str) -> list[str]:
    lines = [line.strip() for line in str(case_context or "").splitlines() if line.strip()]
    result: list[str] = list(lines)
    for index in range(len(lines) - 1):
        result.append(lines[index] + " " + lines[index + 1])
    return result


def match_claimant_identity(case_context: str, claimant: list[str]) -> PartyIdentityMatch | None:
    """Bind an explicit BIN/IIN to the already-selected claimant, never by court type.

    The claimant name comes from the draft. A source fragment is accepted only
    when it contains a distinctive claimant key and an explicit identifier. This
    lets contract roles such as Supplier/Customer be reused safely after the same
    party becomes Plaintiff, while preventing a defendant BIN/IIN from selecting
    the tariff.
    """
    if _clear_party_type(claimant) is not None:
        return None

    keys = _identity_keys(claimant)
    if not keys:
        return None

    matches: list[PartyIdentityMatch] = []
    for fragment in _windows(case_context):
        normalized = _normalized(fragment)
        if not normalized or not any(key in normalized for key in keys):
            continue

        bin_match = _BIN_RE.search(fragment)
        iin_match = _IIN_RE.search(fragment)
        if bin_match and not iin_match:
            matches.append(
                PartyIdentityMatch(
                    kind="legal_entity",
                    identifier_label="БИН",
                    identifier=bin_match.group(1),
                    source_fragment=_ROLE_PREFIX_RE.sub("", fragment).strip(),
                )
            )
        elif iin_match and not bin_match:
            matches.append(
                PartyIdentityMatch(
                    kind="individual",
                    identifier_label="ИИН",
                    identifier=iin_match.group(1),
                    source_fragment=_ROLE_PREFIX_RE.sub("", fragment).strip(),
                )
            )

    if not matches:
        return None

    kinds = {item.kind for item in matches}
    identifiers = {(item.identifier_label, item.identifier) for item in matches}
    if len(kinds) != 1 or len(identifiers) != 1:
        return None
    return matches[0]


def hydrate_claimant_identity(case_context: str, claimant: list[str]) -> PartyIdentityMatch | None:
    """Restore only a source-bound claimant identifier omitted by the model."""
    match = match_claimant_identity(case_context, claimant)
    if match is None:
        return None
    label = f"{match.identifier_label} {match.identifier}"
    if not any(match.identifier in str(item) for item in claimant):
        claimant.append(label)
    return match
