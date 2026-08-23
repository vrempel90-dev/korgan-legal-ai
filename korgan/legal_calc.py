"""Deterministic legal arithmetic for KORGAN.

Anything computable from a verified legal rate belongs here, not in a model
prompt. The model may not invent, round or "remember" these numbers.
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
    "бин", "тоо", "товарищество с ограниченной ответственностью", "ао ",
    "акционерное общество", "юридическое лицо", "юридического лица",
    "индивидуальный предприниматель", " ип ",
)
_AMOUNT_PATTERN = re.compile(
    r"(\d[\d\s ]*(?:[.,]\d{1,2})?)\s*(?:\([^)]*\)\s*)?(?:тенге|теңге|тг\b|₸|kzt)",
    re.IGNORECASE,
)
_ROLE_LINE_RE = re.compile(
    r"(?im)^\s*(истец|заявитель|ответчик|должник|взыскатель|кредитор)\s*:\s*(.*)$"
)
_NEXT_PARTY_INLINE_RE = re.compile(r"\b(?:ответчик|должник|взыскатель|кредитор)\s*:", re.IGNORECASE)
_PAREN_CLAIMANT_RE = re.compile(
    r"(?is)(?:^|\n|\bстороны\s*:\s*)[^;\n:]{0,100}\(\s*(?:истец|заявитель)\s*\)\s*:\s*"
    r"(.{1,500}?)(?=;\s*[^;\n:]{0,100}\(\s*(?:ответчик|должник)\s*\)\s*:|\n|$)"
)
_PARTY_BEFORE_PAREN_CLAIMANT_RE = re.compile(
    r"(?is)(?:^|[;\n])\s*(?P<party>[^;\n]{1,240}?)\s*\(\s*(?:истец|заявитель)\s*\)"
)
_PARTY_BEFORE_DASH_CLAIMANT_RE = re.compile(
    r"(?is)(?:^|[;\n])\s*(?P<party>[^;\n]{1,240}?)\s*[—-]\s*(?:истец|заявитель)\b"
)
_PERSON_NAME_RE = re.compile(r"[А-ЯЁ][а-яё-]+\s+[А-ЯЁ][а-яё-]+(?:\s+[А-ЯЁ][а-яё-]+)?")
_IIN_LABELED_RE = re.compile(r"\bИИН\s*[:\-–]?\s*(\d{12})\b", re.IGNORECASE)
_BIN_LABELED_RE = re.compile(r"\bБИН\s*[:\-–]?\s*(\d{12})\b", re.IGNORECASE)
_BARE_12_DIGITS_RE = re.compile(r"(?<!\d)\d{12}(?!\d)")
# Backwards-compatible private alias for any internal imports/tests that still
# refer to the old name. Party-type decisions no longer rely on this regex.
_IIN_RE = _BARE_12_DIGITS_RE


def calc_gosposhlina_claim(amount: int, is_individual: bool) -> int:
    if amount < 0:
        raise ValueError("Сумма иска не может быть отрицательной")
    rate = RATE_INDIVIDUAL if is_individual else RATE_LEGAL_ENTITY
    return min(round(amount * rate), CAP_MRP * MRP_2026)


def parse_all_amounts_kzt(text: str) -> list[int]:
    """Return every positive currency amount in textual order."""
    amounts: list[int] = []
    for match in _AMOUNT_PATTERN.finditer(text or ""):
        digits = re.sub(r"[\s ]", "", match.group(1)).replace(",", ".")
        try:
            value = float(digits)
        except ValueError:
            continue
        if value > 0:
            amounts.append(int(value))
    return amounts


def parse_amount_kzt(text: str) -> int | None:
    amounts = parse_all_amounts_kzt(text)
    return amounts[0] if amounts else None


def format_kzt(value: int) -> str:
    return f"{value:,}".replace(",", " ") + " тенге"


def _before_next_party(text: str) -> tuple[str, bool]:
    match = _NEXT_PARTY_INLINE_RE.search(text or "")
    if match:
        return text[: match.start()].strip(), True
    return (text or "").strip(), False


def _claimant_segment(case_context: str) -> str:
    if not case_context:
        return ""
    lines = case_context.splitlines()
    collected: list[str] = []
    active = False
    for line in lines:
        match = _ROLE_LINE_RE.match(line)
        if match:
            role = match.group(1).lower()
            if role in {"истец", "заявитель"}:
                active = True
                first, stopped = _before_next_party(match.group(2))
                collected = [first] if first else []
                if stopped:
                    break
                continue
            if active:
                break
        elif active:
            clipped, stopped = _before_next_party(line)
            if clipped:
                collected.append(clipped)
            if stopped:
                break
    segment = "\n".join(item for item in collected if item).strip()
    if segment:
        return segment

    match = re.search(
        r"(?is)(?:^|[;\n])\s*(?:истец|заявитель)\s*:\s*(.{1,500}?)"
        r"(?=(?:[;\n]\s*)(?:ответчик|должник|взыскатель|кредитор)\s*:|$)",
        case_context,
    )
    if match:
        return match.group(1).strip()

    parenthetical = _PAREN_CLAIMANT_RE.search(case_context)
    if parenthetical:
        return parenthetical.group(1).strip()

    party_before_parenthetical = _PARTY_BEFORE_PAREN_CLAIMANT_RE.search(case_context)
    if party_before_parenthetical:
        return party_before_parenthetical.group("party").strip()

    party_before_dash = _PARTY_BEFORE_DASH_CLAIMANT_RE.search(case_context)
    return party_before_dash.group("party").strip() if party_before_dash else ""


def _claimant_has_iin_elsewhere(case_context: str, segment: str) -> bool:
    """Match a claimant named in the role block to an IIN in a later identifier block."""
    name_match = _PERSON_NAME_RE.search(segment or "")
    if not name_match:
        return False
    name = name_match.group(0)
    return bool(
        re.search(
            re.escape(name) + r".{0,80}\bИИН\s*[:\-–]?\s*\d{12}\b",
            case_context,
            re.IGNORECASE | re.DOTALL,
        )
    )


def claimant_is_individual(case_context: str) -> bool | None:
    """Determine claimant type only from role-bound or explicitly labeled IDs.

    A bare 12-digit identifier is ambiguous in Kazakhstan because both ИИН and
    БИН have 12 digits. If the claimant cannot be role-bound, only explicit ИИН
    and БИН labels are used; mixed or unlabeled cases remain fail-closed.
    """
    if not case_context:
        return None

    segment = _claimant_segment(case_context)
    if segment:
        lowered = f" {segment.lower()} "
        if any(marker in lowered for marker in _LEGAL_ENTITY_MARKERS):
            return False
        if _IIN_LABELED_RE.search(segment) or _claimant_has_iin_elsewhere(case_context, segment):
            return True
        return None

    labeled_iins = _IIN_LABELED_RE.findall(case_context)
    labeled_bins = _BIN_LABELED_RE.findall(case_context)
    if labeled_bins and not labeled_iins:
        return False
    if labeled_iins and not labeled_bins:
        return True
    return None


def gosposhlina_line(case_context: str, price_of_claim: str) -> str:
    amount = parse_amount_kzt(price_of_claim)
    if amount is None:
        return NEEDS_CALCULATION_MARKER
    is_individual = claimant_is_individual(case_context)
    if is_individual is None:
        return NEEDS_CALCULATION_MARKER
    duty = calc_gosposhlina_claim(amount, is_individual)
    percent = "1%" if is_individual else "3%"
    return f"{format_kzt(duty)} ({percent} от цены иска, {RATE_SOURCE_ARTICLE})"


ARTICLE_353_SOURCE_URL = "https://adilet.zan.kz/rus/docs/K940001000_/compare"
NB_RATE_SOURCE_URL = "https://nationalbank.kz/ru/news/grafik-prinyatiya-resheniy-po-bazovoy-stavke/rubrics/2365"
ARTICLE_353_LABEL = "статья 353 Гражданского кодекса РК (Общая часть)"
NEEDS_RATE_MARKER = "[ТРЕБУЕТ ПРОВЕРКИ: базовая ставка Национального Банка РК]"
NB_BASE_RATES: tuple[tuple[date, float], ...] = (
    (date(2025, 10, 13), 18.0), (date(2026, 6, 8), 17.0), (date(2026, 7, 27), 16.75),
)
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
        return f"{format_kzt(self.principal)} × {self.rate_percent:g}% × {self.days} дн. / {DAYS_IN_YEAR} = {format_kzt(self.amount)}"

    def period(self) -> str:
        return f"с {self.start.strftime('%d.%m.%Y')} по {self.end.strftime('%d.%m.%Y')}"


def base_rate_on(day: date) -> float | None:
    if day > NB_RATE_TABLE_VALID_THROUGH:
        return None
    rate: float | None = None
    for effective_from, value in NB_BASE_RATES:
        if day >= effective_from:
            rate = value
    return rate


def calc_late_payment_penalty(principal: int, start: date, end: date, *, rate_date: date) -> LatePaymentPenalty | None:
    if principal <= 0:
        raise ValueError("Сумма основного долга должна быть положительной")
    if end < start:
        raise ValueError("Дата окончания периода просрочки раньше её начала")
    rate = base_rate_on(rate_date)
    if rate is None:
        return None
    days = (end - start).days + 1
    amount = round(principal * rate / 100 * days / DAYS_IN_YEAR)
    return LatePaymentPenalty(principal, start, end, rate_date, days, rate, amount)


def late_penalty_line(penalty: LatePaymentPenalty | None) -> str:
    if penalty is None:
        return NEEDS_RATE_MARKER
    return (
        f"{format_kzt(penalty.amount)} за период {penalty.period()} "
        f"({penalty.days} дн.; базовая ставка НБ РК {penalty.rate_percent:g}% "
        f"на {penalty.rate_date.strftime('%d.%m.%Y')}; {ARTICLE_353_LABEL}): {penalty.formula()}"
    )
