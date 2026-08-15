"""Deterministic legal arithmetic for KORGAN.

Anything computable from a rate fixed in law belongs here, not in a model
prompt. The model may not invent, round or "remember" these numbers.

Rate source: статья 665 Налогового кодекса РК (Кодекс РК от 18.07.2025
№ 214-VIII, adilet id K2500000214), действует с 01.01.2026 — ставка по искам
имущественного характера: 1% от суммы иска для физических лиц, 3% для
юридических лиц, но не более 10 000 МРП.

МРП source: Закон РК от 08.12.2025 № 239-VIII «О республиканском бюджете на
2026 - 2028 годы» (adilet id Z2500000239) — 4 325 тенге с 01.01.2026.

Both constants are year-bound and must be re-verified against the official
source when the budget law for the next year enters into force.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

_ONE_DAY = timedelta(days=1)

RATE_SOURCE_ARTICLE = "статья 665 Налогового кодекса РК (Кодекс РК № 214-VIII)"
RATE_SOURCE_URL = "https://adilet.zan.kz/rus/docs/K2500000214"
MRP_SOURCE_URL = "https://adilet.zan.kz/rus/docs/Z2500000239"

MRP_2026 = 4325
RATE_INDIVIDUAL = 0.01
RATE_LEGAL_ENTITY = 0.03
CAP_MRP = 10_000

NEEDS_CALCULATION_MARKER = "[ТРЕБУЕТ РАСЧЁТА ГОСПОШЛИНЫ]"

_LEGAL_ENTITY_MARKERS = (
    "бин",
    "тоо",
    "товарищество с ограниченной ответственностью",
    "ао ",
    "акционерное общество",
    "юридическое лицо",
    "юридического лица",
    "индивидуальный предприниматель",
    " ип ",
)

# «2 400 000 тенге», «2400000 тг», «2 400 000 (два миллиона...) тенге».
_AMOUNT_PATTERN = re.compile(
    r"(\d[\d\s ]*(?:[.,]\d{1,2})?)\s*(?:\([^)]*\)\s*)?(?:тенге|тг\b|kzt)",
    re.IGNORECASE,
)


def calc_gosposhlina_claim(amount: int, is_individual: bool) -> int:
    """State duty for a monetary claim, in tenge.

    ``round`` is Python's banker's rounding, which matters only for a claim
    price ending in exactly half a tiyn — acceptable for a duty stated in
    whole tenge.
    """
    if amount < 0:
        raise ValueError("Сумма иска не может быть отрицательной")
    rate = RATE_INDIVIDUAL if is_individual else RATE_LEGAL_ENTITY
    cap = CAP_MRP * MRP_2026
    return min(round(amount * rate), cap)


def parse_amount_kzt(text: str) -> int | None:
    """Extract a tenge amount from free text; None when it is not unambiguous."""
    if not text:
        return None
    match = _AMOUNT_PATTERN.search(text)
    if not match:
        return None
    digits = re.sub(r"[\s ]", "", match.group(1)).replace(",", ".")
    try:
        value = float(digits)
    except ValueError:
        return None
    if value <= 0:
        return None
    return int(value)


def format_kzt(value: int) -> str:
    """Render 24000 as «24 000 тенге»."""
    return f"{value:,}".replace(",", " ") + " тенге"


def claimant_is_individual(case_context: str) -> bool | None:
    """Decide the duty rate from the case materials, fail-closed.

    Returns None when anything in the materials points at a legal entity: the
    1% / 3% choice then depends on facts the code cannot establish, so the duty
    must not be computed at all.
    """
    if not case_context:
        return None
    lowered = f" {case_context.lower()} "
    if any(marker in lowered for marker in _LEGAL_ENTITY_MARKERS):
        return None
    if "иин" not in lowered:
        return None
    return True


def gosposhlina_line(case_context: str, price_of_claim: str) -> str:
    """Court-ready state duty line, or the explicit «needs calculation» marker.

    Never guesses: if either the claim price or the payer type cannot be
    established deterministically, the marker is returned instead of a number.
    """
    amount = parse_amount_kzt(price_of_claim)
    if amount is None:
        return NEEDS_CALCULATION_MARKER

    is_individual = claimant_is_individual(case_context)
    if is_individual is None:
        return NEEDS_CALCULATION_MARKER

    duty = calc_gosposhlina_claim(amount, is_individual)
    percent = "1%" if is_individual else "3%"
    return f"{format_kzt(duty)} ({percent} от цены иска, {RATE_SOURCE_ARTICLE})"


# --- Неустойка за просрочку денежного обязательства (ст. 353 ГК РК) -----------
#
# Размер исчисляется исходя из базовой ставки Национального Банка РК. The rate
# table is deliberately short: only decisions confirmed for this project are
# listed, and a due date outside the covered range yields no rate at all rather
# than a plausible-looking guess.

NB_RATE_SOURCE = "базовая ставка Национального Банка Республики Казахстан"
INTEREST_SOURCE_ARTICLE = "статья 353 Гражданского кодекса РК (Общая часть)"
NEEDS_RATE_MARKER = "[ТРЕБУЕТ УТОЧНЕНИЯ: базовая ставка Национального Банка РК на дату расчёта]"

# (действует с; ставка, % годовых). Отсортировано по возрастанию даты.
NB_BASE_RATES: tuple[tuple[date, float], ...] = (
    (date(2025, 10, 10), 18.0),
    (date(2026, 6, 5), 17.0),
)

# Дни года для перевода годовой ставки в дневную.
DAYS_IN_YEAR = 365


@dataclass(frozen=True, slots=True)
class LateInterest:
    principal: int
    start: date
    end: date
    days: int
    rate_percent: float
    amount: int

    def formula(self) -> str:
        return (
            f"{format_kzt(self.principal)} × {self.rate_percent:g}% × {self.days} дн. / {DAYS_IN_YEAR} "
            f"= {format_kzt(self.amount)}"
        )

    def period(self) -> str:
        return f"с {self.start.strftime('%d.%m.%Y')} по {self.end.strftime('%d.%m.%Y')}"


def base_rate_on(day: date) -> float | None:
    """NB RK base rate effective on ``day``; None when the date predates the table."""
    rate: float | None = None
    for effective_from, value in NB_BASE_RATES:
        if day >= effective_from:
            rate = value
    return rate


def calc_late_payment_interest(
    principal: int,
    start: date,
    end: date,
    rate_percent: float | None = None,
) -> LateInterest | None:
    """Statutory late-payment interest under статья 353 ГК РК.

    ``start`` is the first day of delay and ``end`` the date the amount is
    stated for (both inclusive). The rate defaults to the one effective on the
    day the obligation should have been performed — the day before delay began,
    which is the base case of the article. Returns None when the rate for that
    date is unknown, so the caller can flag the rate alone rather than drop the
    whole provision.
    """
    if principal <= 0:
        raise ValueError("Сумма основного долга должна быть положительной")
    if end < start:
        raise ValueError("Дата окончания периода просрочки раньше её начала")

    if rate_percent is None:
        rate_percent = base_rate_on(start - _ONE_DAY)
    if rate_percent is None:
        return None

    days = (end - start).days + 1
    amount = round(principal * rate_percent / 100 * days / DAYS_IN_YEAR)
    return LateInterest(
        principal=principal,
        start=start,
        end=end,
        days=days,
        rate_percent=rate_percent,
        amount=amount,
    )


def late_interest_line(interest: LateInterest | None) -> str:
    """Court-ready wording, or the rate-specific verification marker."""
    if interest is None:
        return NEEDS_RATE_MARKER
    return (
        f"{format_kzt(interest.amount)} за период {interest.period()} "
        f"({interest.days} дн., {NB_RATE_SOURCE} {interest.rate_percent:g}% годовых; "
        f"{INTEREST_SOURCE_ARTICLE}): {interest.formula()}"
    )
