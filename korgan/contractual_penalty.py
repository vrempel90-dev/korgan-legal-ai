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

    @property
    def rate_percent(self) -> float:
        return self.terms.rate_percent_per_day

    @property
    def cap_percent(self) -> float | None:
        return self.terms.cap_percent


@dataclass(frozen=True, slots=True)
class TemporalPenaltyResult:
    """Deterministic time-accrual result used by document pipelines.

    ``segments`` deliberately uses the public contract keys (``from``/``to``)
    instead of model-facing prose so the same structure can be logged, tested
    and rendered without an LLM doing any arithmetic.
    """

    segments: list[dict[str, object]]
    total_before_cap: int | None
    cap_amount: int | None
    cap_reached_date: date | None
    total: int | None
    daily_after: int
    outstanding_principal: int
    convention: dict[str, str]
    no_penalty_clause: bool = False


_NUMBER = r"(?P<value>\d+(?:[.,]\d+)?)"
_PERCENT_TOKEN = r"(?:%|процент(?:а|ов)?\b)"
_RATE_BASE_RU = (
    r"(?:от\s+(?:сумм\w*\s+)?(?:"
    r"задолженн\w*|долг\w*|просроченн\w*\s+(?:платеж\w*|обязательств\w*)"
    r")\s*)?"
    r"(?:за\s+кажд\w*\s+(?:календарн\w*\s+)?день(?:\s+просроч\w*)?|в\s+день)\b"
)
_RATE_RE = re.compile(
    rf"{_NUMBER}\s*{_PERCENT_TOKEN}\s*{_RATE_BASE_RU}",
    re.IGNORECASE,
)
_RATE_RE_REVERSED = re.compile(
    rf"(?:за\s+кажд\w*\s+(?:календарн\w*\s+)?день(?:\s+просроч\w*)?|в\s+день)\s*"
    rf"(?:[-—:;,]\s*)?{_NUMBER}\s*{_PERCENT_TOKEN}",
    re.IGNORECASE,
)
_RATE_RE_KK = re.compile(
    rf"{_NUMBER}\s*(?:%|пайыз)\s*"
    r"(?:(?:берешек|қарыз)\s+сомасынан\s*)?"
    r"(?:күніне|әрбір\s+(?:кешіктірілген\s+|мерзімі\s+өткен\s+)?күн\s+үшін)\b",
    re.IGNORECASE,
)
_RATE_RE_KK_REVERSED = re.compile(
    r"(?:тұрақсыздық\s+айыб\w*|өсімпұл\w*)\s*"
    r"(?:күніне|әрбір\s+(?:кешіктірілген\s+|мерзімі\s+өткен\s+)?күн\s+үшін)\s*"
    rf"(?:[-—:;,]\s*)?{_NUMBER}\s*(?:%|пайыз\b)",
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
    """Return the logical contract scope containing ``position``."""
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
    """Parse one explicit contractual daily penalty without guessing missing terms."""
    text = str(case_context or "")
    rate_matches = [
        *_RATE_RE.finditer(text),
        *_RATE_RE_REVERSED.finditer(text),
        *_RATE_RE_KK.finditer(text),
        *_RATE_RE_KK_REVERSED.finditer(text),
    ]
    rates = _unique_numeric(rate_matches)
    if len(rates) != 1:
        return None

    rate_position = min(
        (match.start() for match in rate_matches if _as_float(match.group("value")) == rates[0]),
        default=-1,
    )
    if rate_position < 0:
        return None

    local = text[max(0, rate_position - 320):min(len(text), rate_position + 320)]
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
    terms: ContractualPenaltyTerms | date,
    start: date,
    end: date | ContractualPenaltyTerms,
) -> ContractualPenalty:
    """Calculate contractual penalty; accept legacy argument order during migration."""
    if isinstance(terms, date) and isinstance(end, ContractualPenaltyTerms):
        actual_terms = end
        actual_start = terms
        actual_end = start
    elif isinstance(terms, ContractualPenaltyTerms) and isinstance(end, date):
        actual_terms = terms
        actual_start = start
        actual_end = end
    else:
        raise TypeError("Некорректные аргументы расчёта договорной неустойки")

    if principal <= 0:
        raise ValueError("Сумма основного долга должна быть положительной")
    if actual_terms.rate_percent_per_day <= 0:
        raise ValueError("Ставка договорной неустойки должна быть положительной")
    if actual_terms.cap_percent is not None and actual_terms.cap_percent <= 0:
        raise ValueError("Лимит договорной неустойки должен быть положительным")
    if actual_end < actual_start:
        raise ValueError("Дата окончания периода просрочки раньше даты начала")

    days = (actual_end - actual_start).days + 1
    raw_amount = round(principal * actual_terms.rate_percent_per_day / 100 * days)

    cap_amount: int | None = None
    cap_reached_on: date | None = None
    capped = False
    amount = raw_amount

    if actual_terms.cap_percent is not None:
        cap_amount = round(principal * actual_terms.cap_percent / 100)
        days_to_cap = math.ceil(actual_terms.cap_percent / actual_terms.rate_percent_per_day)
        cap_reached_on = actual_start + timedelta(days=max(days_to_cap - 1, 0))
        capped = raw_amount >= cap_amount
        amount = min(raw_amount, cap_amount)

    return ContractualPenalty(
        principal=principal,
        start=actual_start,
        end=actual_end,
        days=days,
        terms=actual_terms,
        amount=amount,
        capped=capped,
        cap_amount=cap_amount,
        cap_reached_on=cap_reached_on,
    )


def _round_money(value: Decimal) -> int:
    from decimal import ROUND_HALF_UP

    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _ceil_positive(value: Decimal) -> int:
    from decimal import ROUND_CEILING

    return int(value.to_integral_value(rounding=ROUND_CEILING))


def _temporal_convention(payment_allocation: str) -> dict[str, str]:
    return {
        "delay_start": "due_date + 1 calendar day",
        "day_count": "calendar days, both segment endpoints included",
        "payment_day_base": "old principal applies on the payment date",
        "payment_effective": "payment reduces the accrual base from the next calendar day",
        "payment_allocation": payment_allocation,
        "rounding": "ROUND_HALF_UP to whole KZT for reported monetary values",
    }


def calc_temporal_contractual_penalty(
    *,
    base_amount: int,
    due_date: date,
    rate_percent_per_day: float | None,
    cap_percent: float | None,
    payments: list[tuple[date, int]] | None,
    as_of_date: date,
    payment_allocation: str = "principal",
) -> TemporalPenaltyResult:
    """Accrue a contractual daily penalty over a changing principal balance.

    The due date itself is never a delay day: accrual begins on the next
    calendar day. A payment is charged on the old base on its payment date and
    reduces principal from the following day. The allocation policy is an
    explicit parameter; this implementation supports the agreed ``principal``
    policy and fails closed instead of silently applying another order.
    """
    if base_amount < 0:
        raise ValueError("Сумма обязательства не может быть отрицательной")
    if cap_percent is not None and cap_percent <= 0:
        raise ValueError("Ограничитель должен быть положительным")
    if rate_percent_per_day is not None and rate_percent_per_day <= 0:
        raise ValueError("Ставка неустойки должна быть положительной")
    if payment_allocation != "principal":
        raise ValueError(
            "Неподдерживаемый порядок погашения: передайте отдельную реализацию/политику вместо молчаливой подстановки"
        )

    normalized_payments: list[tuple[date, int]] = []
    for payment_date, amount in payments or []:
        if amount <= 0:
            raise ValueError("Сумма платежа должна быть положительной")
        normalized_payments.append((payment_date, int(amount)))
    normalized_payments.sort(key=lambda item: item[0])

    total_paid_through_as_of = sum(amount for payment_date, amount in normalized_payments if payment_date <= as_of_date)
    if total_paid_through_as_of > base_amount:
        raise ValueError("Сумма платежей превышает исходный основной долг")
    outstanding_at_as_of = base_amount - total_paid_through_as_of
    convention = _temporal_convention(payment_allocation)

    if rate_percent_per_day is None:
        return TemporalPenaltyResult(
            segments=[],
            total_before_cap=None,
            cap_amount=None,
            cap_reached_date=None,
            total=None,
            daily_after=0,
            outstanding_principal=outstanding_at_as_of,
            convention=convention,
            no_penalty_clause=True,
        )

    delay_start = due_date + timedelta(days=1)
    rate = Decimal(str(rate_percent_per_day)) / Decimal("100")
    cap_exact = (
        Decimal(base_amount) * Decimal(str(cap_percent)) / Decimal("100")
        if cap_percent is not None
        else None
    )
    cap_amount = _round_money(cap_exact) if cap_exact is not None else None

    if as_of_date < delay_start or base_amount == 0:
        return TemporalPenaltyResult(
            segments=[],
            total_before_cap=0,
            cap_amount=cap_amount,
            cap_reached_date=None,
            total=0,
            daily_after=0,
            outstanding_principal=outstanding_at_as_of,
            convention=convention,
        )

    outstanding = base_amount
    for payment_date, amount in normalized_payments:
        if payment_date < delay_start:
            outstanding -= amount

    payments_by_date: dict[date, int] = {}
    for payment_date, amount in normalized_payments:
        if delay_start <= payment_date <= as_of_date:
            payments_by_date[payment_date] = payments_by_date.get(payment_date, 0) + amount

    segments: list[dict[str, object]] = []
    accrued_exact = Decimal("0")
    cap_reached_date: date | None = None
    cursor = delay_start

    for boundary in [*sorted(payments_by_date), as_of_date]:
        if boundary < cursor:
            continue
        if outstanding > 0:
            days = (boundary - cursor).days + 1
            daily_exact = Decimal(outstanding) * rate
            segment_exact = daily_exact * Decimal(days)
            if (
                cap_exact is not None
                and cap_reached_date is None
                and daily_exact > 0
                and accrued_exact < cap_exact <= accrued_exact + segment_exact
            ):
                days_to_cap = _ceil_positive((cap_exact - accrued_exact) / daily_exact)
                cap_reached_date = cursor + timedelta(days=max(days_to_cap - 1, 0))
            segments.append(
                {
                    "from": cursor,
                    "to": boundary,
                    "base": outstanding,
                    "rate_per_day": _round_money(daily_exact),
                    "days": days,
                    "amount": _round_money(segment_exact),
                }
            )
            accrued_exact += segment_exact

        if boundary in payments_by_date:
            outstanding -= payments_by_date[boundary]
            if outstanding < 0:
                raise ValueError("Платёж уменьшил основной долг ниже нуля")
            cursor = boundary + timedelta(days=1)
        else:
            cursor = boundary + timedelta(days=1)

    total_before_cap = _round_money(accrued_exact)
    total = min(total_before_cap, cap_amount) if cap_amount is not None else total_before_cap
    if cap_exact is not None and accrued_exact < cap_exact:
        cap_reached_date = None

    current_daily = _round_money(Decimal(outstanding_at_as_of) * rate)
    daily_after = 0 if cap_reached_date is not None and cap_reached_date <= as_of_date else current_daily

    return TemporalPenaltyResult(
        segments=segments,
        total_before_cap=total_before_cap,
        cap_amount=cap_amount,
        cap_reached_date=cap_reached_date,
        total=total,
        daily_after=daily_after,
        outstanding_principal=outstanding_at_as_of,
        convention=convention,
    )
