"""Deterministic monetary ledger for civil claims.

The prayer section is written for a judge, not for arithmetic.  It can contain
component amounts and a repeated total in the same sentence.  Treating every
currency token as an independent claim therefore overstates the claim price and
then overstates state duty.

This module converts monetary prayer requests into one canonical ledger without
an LLM call.  It deliberately fails closed when a multi-amount request cannot be
resolved unambiguously: an uncertain claim price must not silently become a
filing-ready number.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

_AMOUNT_RE = re.compile(
    r"(?<!\d)(\d[\d\s\u00a0]*(?:[.,]\d{1,2})?)\s*(?:тенге|теңге|тг\b|₸|kzt)",
    re.IGNORECASE,
)
_STATE_DUTY_RE = re.compile(r"(?:госпошлин\w*|государственн\w*\s+пошлин\w*|мемлекетт(?:ік|iк)\s+баж)", re.IGNORECASE)
_COST_RE = re.compile(
    r"(?:судебн\w*\s+расход\w*|расход\w*\s+(?:на|по)\s+(?:представител|юридическ|оплат)\w*|"
    r"сот\s+шығын\w*|өкіл\w*\s+шығын\w*)",
    re.IGNORECASE,
)
_ALTERNATIVE_RE = re.compile(r"(?:альтернативн\w*|субсидиарн\w*|баламалы)", re.IGNORECASE)
_TOTAL_MARKER_RE = re.compile(
    r"(?:\bитого\b|\bвсего\b|\bобщ(?:ая|ий)\s+сумм\w*\b|\bсуммарн\w*\b|"
    r"\bбарлығы\b|\bжалпы\s+сом\w*\b)",
    re.IGNORECASE,
)
_INCLUDED_RE = re.compile(r"(?:\bв\s+том\s+числе\b|\bиз\s+которых\b|\bоның\s+ішінде\b)", re.IGNORECASE)

_KIND_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("penalty", re.compile(r"(?:неустойк\w*|пен[яию]\b|штраф\w*|тұрақсыздық\s+айыб\w*|өсімпұл\w*|айыппұл\w*)", re.IGNORECASE)),
    ("interest", re.compile(r"(?:процент\w*|сыйақ\w*|ақшаны\s+заңсыз\s+пайдалан)", re.IGNORECASE)),
    ("damages", re.compile(r"(?:убытк\w*|ущерб\w*|материал\w*\s+вред\w*|залал\w*)", re.IGNORECASE)),
    ("moral_damage", re.compile(r"(?:моральн\w*\s+вред\w*|моральдық\s+зиян\w*)", re.IGNORECASE)),
    ("principal", re.compile(r"(?:основн\w*\s+долг\w*|задолженн\w*|предоплат\w*|аванс\w*|предварительн\w*\s+оплат\w*|берешек\w*|алдын\s+ала\s+төлем\w*)", re.IGNORECASE)),
    ("restitution", re.compile(r"(?:возврат\w*|вернут\w*|қайтар\w*)", re.IGNORECASE)),
)


@dataclass(frozen=True, slots=True)
class ClaimMoneyComponent:
    kind: str
    amount: int
    source_request: str


@dataclass(slots=True)
class ClaimMoneyLedger:
    components: list[ClaimMoneyComponent] = field(default_factory=list)
    unresolved_requests: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return sum(item.amount for item in self.components)

    @property
    def resolved(self) -> bool:
        return bool(self.components) and not self.unresolved_requests


def _amount(value: str) -> int:
    raw = re.sub(r"[\s\u00a0]", "", value).replace(",", ".")
    try:
        parsed = Decimal(raw)
    except (InvalidOperation, ValueError):
        return 0
    if parsed <= 0:
        return 0
    return int(parsed.to_integral_value(rounding=ROUND_HALF_UP))


def _kind(text: str, start: int, end: int) -> str:
    # Prefer the nearest semantic label; a wide enough window supports common
    # forms such as "неустойку в размере 996 000 тенге" without allowing a
    # distant label to classify every number in the sentence.
    before = text[max(0, start - 80):start]
    after = text[end:min(len(text), end + 45)]
    for code, pattern in _KIND_PATTERNS:
        if pattern.search(before) or pattern.search(after):
            return code
    return "other"


def _explicit_total_index(text: str, matches: list[re.Match[str]]) -> int | None:
    markers = list(_TOTAL_MARKER_RE.finditer(text))
    if markers:
        # A total is normally written after the marker ("итого: 100"), but
        # Russian/Kazakh prose also permits "100 тенге всего".
        marker = markers[-1]
        after = [idx for idx, match in enumerate(matches) if match.start() >= marker.end() and match.start() - marker.end() <= 90]
        if after:
            return after[0]
        before = [idx for idx, match in enumerate(matches) if match.end() <= marker.start() and marker.start() - match.end() <= 45]
        if before:
            return before[-1]

    # "10 000 + 500 = 10 500 тенге" is an explicit arithmetic total even if
    # the author omitted the word "итого".
    equals = text.rfind("=")
    if equals >= 0:
        after_equals = [idx for idx, match in enumerate(matches) if match.start() > equals]
        if after_equals:
            return after_equals[-1]

    included = _INCLUDED_RE.search(text)
    if included:
        before = [idx for idx, match in enumerate(matches) if match.end() <= included.start()]
        if before:
            return before[-1]
    return None


def _resolved_components(request: str) -> list[ClaimMoneyComponent] | None:
    matches = list(_AMOUNT_RE.finditer(request or ""))
    if not matches:
        return []

    values = [_amount(match.group(1)) for match in matches]
    if any(value <= 0 for value in values):
        return None

    total_index = _explicit_total_index(request, matches)
    if total_index is not None:
        return [ClaimMoneyComponent("total", values[total_index], request)]

    if len(matches) == 1:
        return [ClaimMoneyComponent(_kind(request, matches[0].start(), matches[0].end()), values[0], request)]

    # Detect an unlabelled arithmetic total: component amounts followed or
    # preceded by their exact sum.  This removes the most dangerous historical
    # double-counting pattern without guessing at legal meaning.
    if len(values) >= 3 and values[-1] == sum(values[:-1]):
        return [ClaimMoneyComponent("total", values[-1], request)]
    if len(values) >= 3 and values[0] == sum(values[1:]):
        return [ClaimMoneyComponent("total", values[0], request)]

    kinds = [_kind(request, match.start(), match.end()) for match in matches]
    # Multiple amounts in one prayer line are safe to add only when each one is
    # tied to a different recognised remedy (e.g. principal + penalty).  Two
    # unlabelled figures are ambiguous and must not become a silent calculation.
    if "other" not in kinds and len(set(kinds)) == len(kinds):
        return [
            ClaimMoneyComponent(kind, value, request)
            for kind, value in zip(kinds, values, strict=True)
        ]
    return None


def build_claim_money_ledger(requests: list[str]) -> ClaimMoneyLedger:
    ledger = ClaimMoneyLedger()
    seen_requests: set[str] = set()

    for raw in requests or []:
        request = " ".join(str(raw or "").split()).strip()
        if not request:
            continue
        marker = request.casefold()
        if marker in seen_requests:
            continue
        seen_requests.add(marker)

        if _STATE_DUTY_RE.search(request) or _COST_RE.search(request) or _ALTERNATIVE_RE.search(request):
            continue
        if not _AMOUNT_RE.search(request):
            continue

        resolved = _resolved_components(request)
        if resolved is None:
            ledger.unresolved_requests.append(request)
            continue
        ledger.components.extend(resolved)

    return ledger
