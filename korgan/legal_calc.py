"""Deterministic legal arithmetic for KORGAN.

Anything computable from a verified legal rate belongs here, not in a model
prompt. The model may not invent, round or "remember" these numbers.

State-duty source: статья 665 Налогового кодекса РК (Кодекс РК от 18.07.2025
№ 214-VIII, adilet id K2500000214), действует с 01.01.2026 — ставка по искам
имущественного характера: 1% от суммы иска для физических лиц, 3% для
юридических лиц, но не более 10 000 МРП.

МРП source: Закон РК от 08.12.2025 № 239-VIII «О республиканском бюджете на
2026 - 2028 годы» (adilet id Z2500000239) — 4 325 тенге с 01.01.2026.

Article 353 calculation uses a versioned National Bank rate table.  The table
is intentionally fail-closed: after the next scheduled rate decision it is not
used until the project re-verifies the official National Bank schedule.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

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
    """State duty for a monetary claim, in tenge."""
    if amount < 0:
        raise ValueError("Сумма иска не может быть отрицательной")
    rate = RATE_INDIVIDUAL if is_individual else RATE_LEGAL_ENTITY
    cap = CAP_MRP * MRP_2026
    return min(round(amount * rate), cap)


def parse_amount_kzt(text: str) -> int | None:
    """Extract the first explicit tenge amount from free text."""
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
    """Decide the duty rate from the case materials, fail-closed."""
    if not case_context:
        return None
    lowered = f" {case_context.lower()} "
    if any(marker in lowered for marker in _LEGAL_ENTITY_MARKERS):
        return None
    if "иин" not in lowered:
        return None
    return True


def gosposhlina_line(case_context: str, price_of_claim: str) -> str:
    """Court-ready state duty line, or the explicit needs-calculation marker."""
    amount = parse_amount_kzt(price_of_claim)
    if amount is None:
        return NEEDS_CALCULATION_MARKER

    is_individual = claimant_is_individual(case_context)
    if is_individual is None:
        return NEEDS_CALCULATION_MARKER

    duty = calc_gosposhlina_claim(amount, is_individual)
    percent = "1%" if is_individual else "3%"
    return f"{format_kzt(duty)} ({percent} от цены иска, {RATE_SOURCE_ARTICLE})"


# --- Неустойка за просрочку денежного обязательства (ст. 353 ГК РК) ---------

ARTICLE_353_SOURCE_URL = "https://adilet.zan.kz/rus/docs/K940001000_/compare"
NB_RATE_SOURCE_URL = "https://nationalbank.kz/ru/news/grafik-prinyatiya-resheniy-po-bazovoy-stavke/rubrics/2365"
ARTICLE_353_LABEL = "статья 353 Гражданского кодекса РК (Общая часть)"
NEEDS_RATE_MARKER = "[ТРЕБУЕТ ПРОВЕРКИ: базовая ставка Национального Банка РК]"

# Дата установления ставки -> ставка, % годовых. Проверено по официальному
# графику Национального Банка 16.08.2026. До 13.10.2025 таблица намеренно не
# покрывает период: код должен вернуть NEEDS_VERIFICATION, а не угадывать.
NB_BASE_RATES: tuple[tuple[date, float], ...] = (
    (date(2025, 10, 13), 18.0),
    (date(2026, 6, 8), 17.0),
    (date(2026, 7, 27), 16.75),
)

# Следующее плановое решение НБ РК заявлено на 04.09.2026. После 03.09.2026
# справочник считается просроченным до нового подтверждения.
NB_RATE_TABLE_VALID_THROUGH = date(2026, 9, 3)
DAYS_IN_YEAR = 365


@dataclass(frozen=True, slots=True)
class LatePaymentPenalty:
    principal: int
    start: date
    end: date
    rate_date: date
    days: int
    rate_percent: float
    amount: int

    def formula(self) -> str:
        return (
            f"{format_kzt(self.principal)} × {self.rate_percent:g}% × "
            f"{self.days} дн. / {DAYS_IN_YEAR} = {format_kzt(self.amount)}"
        )

    def period(self) -> str:
        return f"с {self.start.strftime('%d.%m.%Y')} по {self.end.strftime('%d.%m.%Y')}"


def base_rate_on(day: date) -> float | None:
    """Official NB RK base rate effective on ``day`` within the verified table."""
    if day > NB_RATE_TABLE_VALID_THROUGH:
        return None
    rate: float | None = None
    for effective_from, value in NB_BASE_RATES:
        if day >= effective_from:
            rate = value
    return rate


def calc_late_payment_penalty(
    principal: int,
    start: date,
    end: date,
    *,
    rate_date: date,
) -> LatePaymentPenalty | None:
    """Calculate Article 353 penalty using the creditor's filing-date rate choice.

    Article 353 permits, in judicial recovery, use of the National Bank base
    rate on the filing date, judgment date, or actual-payment date at the
    creditor's choice.  KORGAN's deterministic court-draft path uses the
    filing-date option because that date is known when the draft is created.
    """
    if principal <= 0:
        raise ValueError("Сумма основного долга должна быть положительной")
    if end < start:
        raise ValueError("Дата окончания периода просрочки раньше её начала")
    rate = base_rate_on(rate_date)
    if rate is None:
        return None
    days = (end - start).days + 1
    amount = round(principal * rate / 100 * days / DAYS_IN_YEAR)
    return LatePaymentPenalty(
        principal=principal,
        start=start,
        end=end,
        rate_date=rate_date,
        days=days,
        rate_percent=rate,
        amount=amount,
    )


def late_penalty_line(penalty: LatePaymentPenalty | None) -> str:
    """Court-facing deterministic calculation or a fail-closed marker."""
    if penalty is None:
        return NEEDS_RATE_MARKER
    return (
        f"{format_kzt(penalty.amount)} за период {penalty.period()} "
        f"({penalty.days} дн.; базовая ставка НБ РК {penalty.rate_percent:g}% "
        f"на {penalty.rate_date.strftime('%d.%m.%Y')}; {ARTICLE_353_LABEL}): "
        f"{penalty.formula()}"
    )
