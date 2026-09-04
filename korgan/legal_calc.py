"""Deterministic legal arithmetic for KORGAN.

Anything computable from a verified legal rate belongs here, not in a model
prompt. The model may not invent, round or "remember" these numbers.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any

_RATES_PATH = Path(__file__).resolve().parent / "data" / "rates.json"


def _load_rates_data() -> dict[str, Any]:
    """Load legal arithmetic inputs from the repository data contract.

    Numeric legal rates intentionally live in ``data/rates.json`` so changing a
    statutory indicator or National Bank rate does not require a code edit.
    Import fails closed when the data contract is malformed instead of silently
    falling back to remembered constants.
    """
    try:
        payload = json.loads(_RATES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Не удалось загрузить справочник ставок: {_RATES_PATH}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("Справочник ставок должен быть JSON-объектом")
    return payload


def _required_mapping(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise RuntimeError(f"В справочнике ставок отсутствует объект {key}")
    return value


def _required_rows(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = payload.get(key)
    if not isinstance(value, list) or not value or not all(isinstance(item, dict) for item in value):
        raise RuntimeError(f"В справочнике ставок отсутствует список {key}")
    return value


_RATES_DATA = _load_rates_data()
_STATE_DUTY_DATA = _required_mapping(_RATES_DATA, "state_duty")
_MRP_ROWS = _required_rows(_RATES_DATA, "mrp")
_NB_RATE_ROWS = _required_rows(_RATES_DATA, "nb_base_rate")

RATE_SOURCE_ARTICLE = str(_STATE_DUTY_DATA["source"])
RATE_SOURCE_URL = str(_STATE_DUTY_DATA["source_url"])
MRP_SOURCE_URL = str(_MRP_ROWS[-1]["source_url"])
MRP_2026 = int(_MRP_ROWS[-1]["value"])
RATE_INDIVIDUAL = float(_STATE_DUTY_DATA["individual_rate"])
RATE_LEGAL_ENTITY = float(_STATE_DUTY_DATA["legal_entity_rate"])
CAP_MRP_INDIVIDUAL = int(_STATE_DUTY_DATA["individual_cap_mrp"])
CAP_MRP_LEGAL_ENTITY = int(_STATE_DUTY_DATA["legal_entity_cap_mrp"])
NONPROPERTY_DUTY_MRP = float(_STATE_DUTY_DATA["nonproperty_mrp"])
# Backwards-compatible alias. Historically KORGAN had one cap for both party
# types; callers that still import CAP_MRP now receive the individual cap.
CAP_MRP = CAP_MRP_INDIVIDUAL
NEEDS_CALCULATION_MARKER = "[ТРЕБУЕТ РАСЧЁТА ГОСПОШЛИНЫ]"

_LEGAL_ENTITY_ABBREVIATIONS = ("бин", "тоо", "ао")
_LEGAL_ENTITY_PHRASES = (
    "товарищество с ограниченной ответственностью",
    "акционерное общество",
    "юридическое лицо",
    "юридического лица",
)
_INDIVIDUAL_ENTREPRENEUR_RE = re.compile(
    r"(?i)(?:\bиндивидуальн\w*\s+предпринимател\w*\b|(?<!\w)ип(?!\w))"
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
_IIN_RE = _BARE_12_DIGITS_RE


def _round_tenge(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def calc_gosposhlina_claim(amount: int, is_individual: bool) -> int:
    """State duty for an ordinary property claim under Article 665(1)(1).

    Physical persons (including an individual entrepreneur in an ordinary civil
    property claim) pay 1% capped at 10,000 MRP. Legal entities pay 3% capped at
    20,000 MRP. Special administrative/tax categories must use their own rule and
    are intentionally not folded into this helper.
    """
    if amount < 0:
        raise ValueError("Сумма иска не может быть отрицательной")
    rate = RATE_INDIVIDUAL if is_individual else RATE_LEGAL_ENTITY
    cap_mrp = CAP_MRP_INDIVIDUAL if is_individual else CAP_MRP_LEGAL_ENTITY
    cap = Decimal(cap_mrp) * Decimal(MRP_2026)
    calculated = Decimal(amount) * Decimal(str(rate))
    return min(_round_tenge(calculated), int(cap))


def calc_nonproperty_state_duty(*, demands: int = 1) -> int:
    """Duty for independently chargeable non-property claims.

    Article 665 sets 0.5 MRP for a non-property claim. A mixed filing may need
    both its property duty and the non-property component; callers must provide
    the count only when the demands are legally independent and separately
    chargeable. Ambiguous classification should remain fail-closed upstream.
    """
    if demands < 0:
        raise ValueError("Количество неимущественных требований не может быть отрицательным")
    return _round_tenge(Decimal(MRP_2026) * Decimal(str(NONPROPERTY_DUTY_MRP)) * Decimal(demands))


def calc_mixed_state_duty(amount: int, is_individual: bool, *, nonproperty_demands: int = 1) -> int:
    """Property duty plus separately chargeable non-property component."""
    return calc_gosposhlina_claim(amount, is_individual) + calc_nonproperty_state_duty(demands=nonproperty_demands)


def parse_all_amounts_kzt(text: str) -> list[int]:
    """Return every positive currency amount in textual order.

    Fractional tenge are rounded to whole tenge with ``ROUND_HALF_UP`` so money
    parsing never silently truncates kopecks before claim-price or duty math.
    ``to_integral_value`` avoids Decimal context-precision failures on unusually
    long but syntactically valid user-provided amounts.
    """
    amounts: list[int] = []
    for match in _AMOUNT_PATTERN.finditer(text or ""):
        digits = re.sub(r"[\s ]", "", match.group(1)).replace(",", ".")
        try:
            value = Decimal(digits)
        except (InvalidOperation, ValueError):
            continue
        if value > 0:
            amounts.append(int(value.to_integral_value(rounding=ROUND_HALF_UP)))
    return amounts


def parse_amount_kzt(text: str) -> int | None:
    amounts = parse_all_amounts_kzt(text)
    return amounts[0] if amounts else None


def claim_price_amount(price_of_claim: str) -> int | None:
    """Цена иска из строки — только если она определяется однозначно.

    Поле цены иска пишется свободным текстом и часто содержит не одну сумму,
    а итог со слагаемыми («1 200 000 тенге долга и 92 400 тенге неустойки,
    итого 1 292 400 тенге»). Брать первую попавшуюся сумму нельзя: госпошлина
    тогда считается от слагаемого, а не от цены иска, и документ уходит в суд
    с заниженной пошлиной, поданной как точный расчёт.

    Одна сумма — она и есть цена иска. Если сумм несколько, цена иска берётся
    только тогда, когда ровно одна из них арифметически равна сумме остальных,
    то есть является их итогом. Иначе величина не определена: код не угадывает
    её и не складывает то, что не обязано быть слагаемыми, — вызывающая сторона
    обязана обработать None как «требует расчёта».
    """
    amounts = parse_all_amounts_kzt(price_of_claim)
    if not amounts:
        return None
    if len(amounts) == 1:
        return amounts[0]
    total = sum(amounts)
    totals = [value for value in amounts if value * 2 == total]
    return totals[0] if len(totals) == 1 else None


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


def _has_legal_entity_marker(segment: str) -> bool:
    lowered = (segment or "").lower()
    if any(phrase in lowered for phrase in _LEGAL_ENTITY_PHRASES):
        return True
    return any(
        re.search(rf"(?<!\w){re.escape(marker)}(?!\w)", lowered)
        for marker in _LEGAL_ENTITY_ABBREVIATIONS
    )


def claimant_is_individual(case_context: str) -> bool | None:
    """Determine claimant type only from role-bound or explicitly labeled IDs.

    An individual entrepreneur remains a physical person for the ordinary civil
    property-claim rate. Special Article 665 administrative/tax-notice claims
    have their own IP rate and must not use this ordinary helper.
    """
    if not case_context:
        return None

    segment = _claimant_segment(case_context)
    if segment:
        if _has_legal_entity_marker(segment):
            return False
        if _INDIVIDUAL_ENTREPRENEUR_RE.search(segment):
            return True
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
    """Render the deterministic duty line for an ordinary property claim."""
    amount = claim_price_amount(price_of_claim)
    if amount is None:
        return NEEDS_CALCULATION_MARKER
    is_individual = claimant_is_individual(case_context)
    if is_individual is None:
        return NEEDS_CALCULATION_MARKER
    duty = calc_gosposhlina_claim(amount, is_individual)
    percent = f"{RATE_INDIVIDUAL * 100:g}%" if is_individual else f"{RATE_LEGAL_ENTITY * 100:g}%"
    cap_mrp = CAP_MRP_INDIVIDUAL if is_individual else CAP_MRP_LEGAL_ENTITY
    return (
        f"{format_kzt(duty)} ({percent} от цены иска; максимум {cap_mrp:,} МРП; "
        f"{RATE_SOURCE_ARTICLE})"
    ).replace(",", " ")


ARTICLE_353_SOURCE_URL = "https://adilet.zan.kz/rus/docs/K940001000_/compare"
NB_RATE_SOURCE_URL = str(_NB_RATE_ROWS[-1].get("source_url", ""))
ARTICLE_353_LABEL = "статья 353 Гражданского кодекса РК (Общая часть)"
NEEDS_RATE_MARKER = "[ТРЕБУЕТ ПРОВЕРКИ: базовая ставка Национального Банка РК]"
NB_BASE_RATES: tuple[tuple[date, float], ...] = tuple(
    (date.fromisoformat(str(item["from"])), float(item["value"]))
    for item in _NB_RATE_ROWS
)
NB_RATE_TABLE_VALID_THROUGH = date.fromisoformat(str(_RATES_DATA["nb_base_rate_valid_through"]))
DAYS_IN_YEAR = int(_RATES_DATA["days_in_year"])


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
