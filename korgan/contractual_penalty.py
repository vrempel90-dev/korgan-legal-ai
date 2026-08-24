from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation


@dataclass(frozen=True, slots=True)
class ContractualPenaltyTerms:
    rate_percent_per_day: float
    cap_percent: float | None
    clause: str


@dataclass(frozen=True, slots=True)
class ContractualPenalty:
    principal: int
    start: date
    end: date
    days: int
    terms: ContractualPenaltyTerms
    amount: int
    capped: bool
    cap_amount: int | None
    cap_reached_on: date | None


_NUMBER = r"(?P<value>\d+(?:[.,]\d+)?)"
_PERCENT_TOKEN = r"(?:%|процент(?:а|ов)?\b)"
_RATE_RE = re.compile(
    rf"{_NUMBER}\s*{_PERCENT_TOKEN}\s*"
    r"(?:от\s+(?:сумм\w*\s+)?(?:задолженн\w*|долг\w*)\s*)?"
    r"(?:за\s+кажд\w*\s+день(?:\s+просроч\w*)?|в\s+день)\b",
    re.IGNORECASE,
)
_RATE_RE_REVERSED = re.compile(
    rf"(?:за\s+кажд\w*\s+день(?:\s+просроч\w*)?|в\s+день)\s*"
    rf"(?:[-—:;,]\s*)?{_NUMBER}\s*{_PERCENT_TOKEN}",
    re.IGNORECASE,
)
_RATE_RE_KK = re.compile(
    rf"{_NUMBER}\s*(?:%|пайыз)\s*"
    r"(?:(?:берешек|қарыз)\s+сомасынан\s*)?"
    r"(?:күніне|әрбір\s+(?:кешіктірілген\s+|мерзімі\s+өткен\s+)?күн\s+үшін)\b",
    re.IGNORECASE,
)
_CAP_RE = re.compile(
    rf"(?:но\s+)?(?:не\s+более|не\s+свыше|не\s+превыша\w*)\s*{_NUMBER}\s*{_PERCENT_TOKEN}",
    re.IGNORECASE,
)
_CAP_RE_KK = re.compile(
    rf"{_NUMBER}\s*(?:%|пайыз)\s*(?:-\s*)?(?:дан|ден)?\s*(?:аспай\w*|артық\s+емес)",
    re.IGNORECASE,
)
_CLAUSE_RE = re.compile(
    r"(?:пункт(?:ом|у|а|е)?|п\.)\s*(?P<clause>\d+(?:\.\d+){1,3})",
    re.IGNORECASE,
)
_CLAUSE_RE_KK = re.compile(
    r"(?P<clause>\d+(?:\.\d+){1,3})\s*[-–]?\s*тарма\w*",
    re.IGNORECASE,
)
_CONTRACT_RE = re.compile(r"\b(?:договор\w*|шарт\w*)\b", re.IGNORECASE)


def _as_float(raw: str) -> float | None:
    try:
        value = Decimal((raw or "").replace(",", "."))
    except (InvalidOperation, ValueError):
        return None
    if value <= 0:
        return None
    return float(value)


def _unique_numeric(matches: list[re.Match[str]]) -> list[float]:
    values: list[float] = []
    for match in matches:
        value = _as_float(match.group("value"))
        if value is None:
            continue
        if not any(math.isclose(value, existing, rel_tol=0.0, abs_tol=1e-12) for existing in values):
            values.append(value)
    return values


def _clause_matches(text: str, start: int = 0, end: int | None = None) -> list[re.Match[str]]:
    stop = len(text) if end is None else end
    matches = [*_CLAUSE_RE.finditer(text, start, stop), *_CLAUSE_RE_KK.finditer(text, start, stop)]
    matches.sort(key=lambda match: match.start())
    return matches


def _nearest_clause(text: str, position: int) -> str:
    preceding = [match for match in _clause_matches(text) if match.start() <= position]
    if preceding:
        return preceding[-1].group("clause")

    candidates: list[tuple[int, str]] = []
    start = max(0, position - 240)
    end = min(len(text), position + 240)
    for match in _clause_matches(text, start, end):
        candidates.append((abs(match.start() - position), match.group("clause")))
    if not candidates:
        return ""
    candidates.sort(key=lambda item: item[0])
    best_distance = candidates[0][0]
    best = {clause for distance, clause in candidates if distance == best_distance}
    return next(iter(best)) if len(best) == 1 else ""


def _paragraph_for_position(text: str, position: int) -> str:
    """Return the logical contract scope containing ``position``.

    Prefer the numbered clause that owns the rate, so a cap from the next
    contract clause cannot leak into this calculation even when DOCX/PDF text
    separates clauses with only one newline. A long numbered clause remains the
    owner regardless of character distance to the rate.
    """
    if not text:
        return ""

    clause_matches = _clause_matches(text)
    preceding = [match for match in clause_matches if match.start() <= position]
    if preceding:
        anchor = preceding[-1]
        end = len(text)
        for candidate in clause_matches:
            if candidate.start() > position:
                end = candidate.start()
                break
        return text[anchor.start():end]

    separators = list(re.finditer(r"\n\s*\n", text))
    start = 0
    end = len(text)
    for separator in separators:
        if separator.end() <= position:
            start = separator.end()
            continue
        if separator.start() >= position:
            end = separator.start()
            break
    return text[start:end]


def parse_contractual_penalty_terms(case_context: str) -> ContractualPenaltyTerms | None:
    """Parse an explicit contractual daily penalty without guessing missing terms.

    The parser is deliberately fail-closed. It accepts exactly one distinct
    daily rate and requires contractual wording near that rate. If different
    rates or different caps are present in the same clause, no terms are selected.
    Russian and Kazakh contractual formulations are supported deterministically.
    """
    text = str(case_context or "")
    rate_matches = [*_RATE_RE.finditer(text), *_RATE_RE_REVERSED.finditer(text), *_RATE_RE_KK.finditer(text)]
    rates = _unique_numeric(rate_matches)
    if len(rates) != 1:
        return None

    rate_position = min(
        (match.start() for match in rate_matches if _as_float(match.group("value")) == rates[0]),
        default=-1,
    )
    if rate_position < 0:
        return None

    local = text[max(0, rate_position - 260):min(len(text), rate_position + 260)]
    paragraph = _paragraph_for_position(text, rate_position)
    if not _CONTRACT_RE.search(local) and not _CONTRACT_RE.search(paragraph):
        return None

    cap_matches = [*_CAP_RE.finditer(paragraph), *_CAP_RE_KK.finditer(paragraph)]
    caps = _unique_numeric(cap_matches)
    if len(caps) > 1:
        return None
    cap_percent = caps[0] if caps else None

    return ContractualPenaltyTerms(
        rate_percent_per_day=rates[0],
        cap_percent=cap_percent,
        clause=_nearest_clause(text, rate_position),
    )


def calc_contractual_penalty(
    principal: int,
    terms: ContractualPenaltyTerms,
    start: date,
    end: date,
) -> ContractualPenalty:
    if principal <= 0:
        raise ValueError("Сумма основного долга должна быть положительной")
    if terms.rate_percent_per_day <= 0:
        raise ValueError("Ставка договорной неустойки должна быть положительной")
    if terms.cap_percent is not None and terms.cap_percent <= 0:
        raise ValueError("Лимит договорной неустойки должен быть положительным")
    if end < start:
        raise ValueError("Дата окончания периода просрочки раньше даты начала")

    days = (end - start).days + 1
    raw_amount = round(principal * terms.rate_percent_per_day / 100 * days)

    cap_amount: int | None = None
    cap_reached_on: date | None = None
    capped = False
    amount = raw_amount

    if terms.cap_percent is not None:
        cap_amount = round(principal * terms.cap_percent / 100)
        days_to_cap = math.ceil(terms.cap_percent / terms.rate_percent_per_day)
        cap_reached_on = start + timedelta(days=max(days_to_cap - 1, 0))
        capped = raw_amount >= cap_amount
        amount = min(raw_amount, cap_amount)

    return ContractualPenalty(
        principal=principal,
        start=start,
        end=end,
        days=days,
        terms=terms,
        amount=amount,
        capped=capped,
        cap_amount=cap_amount,
        cap_reached_on=cap_reached_on,
    )
