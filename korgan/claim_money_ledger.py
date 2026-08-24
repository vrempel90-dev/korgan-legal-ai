"""Deterministic monetary ledger for civil claims.

The prayer section is written for a judge, not for arithmetic. It can contain
component amounts and a repeated total in the same sentence. Treating every
currency token as an independent claim therefore overstates the claim price and
then overstates state duty.

This module converts monetary prayer requests into one canonical ledger without
an LLM call. It deliberately fails closed when a multi-amount request cannot be
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
_STATE_DUTY_RE = re.compile(
    r"(?:госпошлин\w*|государственн\w*\s+пошлин\w*|мемлекетт(?:ік|iк)\s+баж)",
    re.IGNORECASE,
)
_COST_RE = re.compile(
    r"(?:судебн\w*\s+(?:расход\w*|издерж\w*)|"
    r"(?:расход\w*|издерж\w*)\s+(?:на|по)\s+(?:(?:оплат\w*|услуг\w*)\s+){0,2}"
    r"(?:представител\w*|адвокат\w*|юрист\w*|юридическ\w*|эксперт\w*|специалист\w*|переводчик\w*)|"
    r"расход\w*\s+по\s+делу|сот\s+шығын\w*|өкіл\w*\s+шығын\w*)",
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
_NONPROPERTY_MONEY_KINDS = frozenset({"moral_damage"})


@dataclass(frozen=True, slots=True)
class ClaimMoneyComponent:
    kind: str
    amount: int
    source_request: str
    included_in_claim_price: bool = True


@dataclass(slots=True)
class ClaimMoneyLedger:
    components: list[ClaimMoneyComponent] = field(default_factory=list)
    unresolved_requests: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return sum(item.amount for item in self.components if item.included_in_claim_price)

    @property
    def nonproperty_money_components(self) -> list[ClaimMoneyComponent]:
        return [item for item in self.components if not item.included_in_claim_price]

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
    """Bind an amount to the nearest recognised remedy label."""
    candidates: list[tuple[int, int, int, str]] = []
    for order, (code, pattern) in enumerate(_KIND_PATTERNS):
        for match in pattern.finditer(text or ""):
            if match.end() <= start:
                distance = start - match.end()
                if distance <= 80:
                    candidates.append((distance, 0, order, code))
            elif match.start() >= end:
                distance = match.start() - end
                if distance <= 45:
                    candidates.append((distance, 1, order, code))
            else:
                candidates.append((0, 0, order, code))
    if not candidates:
        return "other"
    return min(candidates)[3]


def _component(kind: str, amount: int, request: str) -> ClaimMoneyComponent:
    return ClaimMoneyComponent(
        kind=kind,
        amount=amount,
        source_request=request,
        included_in_claim_price=kind not in _NONPROPERTY_MONEY_KINDS,
    )


def _explicit_total_index(text: str, matches: list[re.Match[str]]) -> int | None:
    markers = list(_TOTAL_MARKER_RE.finditer(text))
    if markers:
        marker = markers[-1]
        after = [
            idx for idx, match in enumerate(matches)
            if match.start() >= marker.end() and match.start() - marker.end() <= 90
        ]
        if after:
            return after[0]
        before = [
            idx for idx, match in enumerate(matches)
            if match.end() <= marker.start() and marker.start() - match.end() <= 45
        ]
        if before:
            return before[-1]

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


def _component_list(
    request: str,
    matches: list[re.Match[str]],
    values: list[int],
    indices: list[int],
) -> list[ClaimMoneyComponent] | None:
    kinds = [_kind(request, matches[idx].start(), matches[idx].end()) for idx in indices]
    if "other" in kinds or len(set(kinds)) != len(kinds):
        return None
    return [_component(kind, values[idx], request) for kind, idx in zip(kinds, indices, strict=True)]


def _resolved_components(request: str) -> list[ClaimMoneyComponent] | None:
    matches = list(_AMOUNT_RE.finditer(request or ""))
    if not matches:
        return []

    values = [_amount(match.group(1)) for match in matches]
    if any(value <= 0 for value in values):
        return None

    total_index = _explicit_total_index(request, matches)
    if total_index is not None:
        component_indices = [idx for idx in range(len(matches)) if idx != total_index]
        must_match_components = bool(
            (_TOTAL_MARKER_RE.search(request) or "=" in request)
            and not _INCLUDED_RE.search(request)
        )
        if component_indices:
            if must_match_components and values[total_index] != sum(values[idx] for idx in component_indices):
                return None
            components = _component_list(request, matches, values, component_indices)
            # A textual total that mixes property money with a non-property
            # moral-damage amount is not the legal claim price. Keep the
            # independently labelled components and ignore the prose total.
            if components is not None and any(not item.included_in_claim_price for item in components):
                return components
        return [_component("total", values[total_index], request)]

    if len(matches) == 1:
        return [_component(_kind(request, matches[0].start(), matches[0].end()), values[0], request)]

    if len(values) >= 3 and values[-1] == sum(values[:-1]):
        components = _component_list(request, matches, values, list(range(len(values) - 1)))
        if components is not None and any(not item.included_in_claim_price for item in components):
            return components
        return [_component("total", values[-1], request)]
    if len(values) >= 3 and values[0] == sum(values[1:]):
        components = _component_list(request, matches, values, list(range(1, len(values))))
        if components is not None and any(not item.included_in_claim_price for item in components):
            return components
        return [_component("total", values[0], request)]

    return _component_list(request, matches, values, list(range(len(matches))))


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

        if _STATE_DUTY_RE.search(request) or _COST_RE.search(request):
            continue
        if not _AMOUNT_RE.search(request):
            continue
        if _ALTERNATIVE_RE.search(request):
            # Alternative monetary relief can affect the price depending on the
            # legal relationship between primary and fallback remedies. Silently
            # dropping it can understate both price and duty, so classification
            # must remain explicit before filing-ready status.
            ledger.unresolved_requests.append(request)
            continue

        resolved = _resolved_components(request)
        if resolved is None:
            ledger.unresolved_requests.append(request)
            continue
        ledger.components.extend(resolved)

    return ledger
