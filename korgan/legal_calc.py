"""Deterministic legal arithmetic for KORGAN.

Court-duty arithmetic is sourced from ``korgan/data/rates.json`` through
``korgan.legal.calc``.  The LLM never chooses a tariff, MRP, cap or amount.
When claim classification or the rate period is not safe, the calculator fails
closed and the court document is marked for verification instead of guessing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable

from korgan.legal.calc import RateUnavailable, Rates, load_rates, state_duty

RATE_SOURCE_URL = "https://adilet.zan.kz/rus/docs/K2500000214"
MRP_SOURCE_URL = "https://adilet.zan.kz/rus/docs/Z2500000239"
GPK_ARTICLE_106_URL = "https://adilet.zan.kz/rus/docs/K1500000377"
NEEDS_CALCULATION_MARKER = "[ТРЕБУЕТ РАСЧЁТА ГОСПОШЛИНЫ]"

# Compatibility constants for existing callers/tests. Their values are loaded
# from the same dated configuration used by production, not duplicated here.
_DEFAULT_RATES = load_rates()
_DEFAULT_MRP = _DEFAULT_RATES.mrp_on(_DEFAULT_RATES.duty_valid_from)
RATE_SOURCE_ARTICLE = _DEFAULT_RATES.duty_source
MRP_2026 = int(_DEFAULT_MRP.value)
RATE_INDIVIDUAL = _DEFAULT_RATES.duty_individual_rate
RATE_LEGAL_ENTITY = _DEFAULT_RATES.duty_legal_entity_rate
CAP_MRP = _DEFAULT_RATES.duty_individual_cap_mrp
CAP_MRP_LEGAL_ENTITY = _DEFAULT_RATES.duty_legal_entity_cap_mrp
NON_PROPERTY_MRP = Decimal(str(_DEFAULT_RATES.duty_non_property_mrp))
DIVORCE_MRP = Decimal(str(_DEFAULT_RATES.duty_divorce_mrp))
STATE_DUTY_VALID_FROM = _DEFAULT_RATES.duty_valid_from
STATE_DUTY_VALID_THROUGH = _DEFAULT_RATES.duty_valid_through

_LEGAL_ENTITY_MARKERS = (
    "бин", "тоо", "товарищество с ограниченной ответственностью", "ао ",
    "акционерное общество", "юридическое лицо", "юридического лица",
    "производственный кооператив", "общественное объединение", "фонд ",
)
_IP_MARKERS = (
    "индивидуальный предприниматель", "индивидуального предпринимателя",
    "ип ", "и.п.",
)
_AMOUNT_PATTERN = re.compile(
    r"(\d[\d\s ]*(?:[.,]\d{1,2})?)\s*(?:\([^)]*\)\s*)?(?:тенге|тг\b|kzt)",
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
_PERSON_NAME_RE = re.compile(r"[А-ЯЁ][а-яё-]+\s+[А-ЯЁ][а-яё-]+(?:\s+[А-ЯЁ][а-яё-]+)?")
_IIN_RE = re.compile(r"(?<!\d)\d{12}(?!\d)")
_STATE_DUTY_RE = re.compile(r"(?:\bгоспошлин\w*\b|\bгосударственн\w*\s+пошлин\w*\b)", re.IGNORECASE)

# A strong marker itself is an independent non-property remedy, even when the
# same request also contains a monetary consequence. Generic "обязать" is only
# non-property when that request has no priced monetary obligation.
_STRONG_NON_PROPERTY_MARKERS = (
    "расторгнуть договор",
    "выселить",
    "вселить",
    "освободить имущество от ареста",
    "продлить срок принятия наследства",
    "изменить договор найма",
    "расторгнуть договор найма",
)
_GENERIC_NON_PROPERTY_MARKERS = ("обязать ответчика", "обязать ")
_MONETARY_OBLIGATION_MARKERS = (
    "долг", "денеж", "тенге", "тг", "вернуть займ", "возвратить займ",
    "вернуть денеж", "возвратить денеж", "взыскать",
)
_AMBIGUOUS_CLASSIFICATION_MARKERS = (
    "признать сделку недействитель",
    "признать договор недействитель",
    "признать право собственности",
)


def _round_tenge(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _config(rates: Rates | None) -> Rates:
    return rates or load_rates()


def _mrp(multiplier: Decimal | float | int, *, rates: Rates, day: date) -> int:
    rates.ensure_duty_valid_on(day)
    value = rates.mrp_on(day).value
    return _round_tenge(Decimal(str(value)) * Decimal(str(multiplier)))


def calc_gosposhlina_claim(
    amount: int,
    is_individual: bool,
    *,
    rates: Rates | None = None,
    day: date | None = None,
) -> int:
    """State duty for an ordinary property claim under current configured law."""
    if amount < 0:
        raise ValueError("Сумма иска не может быть отрицательной")
    return state_duty(
        amount,
        is_individual=is_individual,
        rates=_config(rates),
        day=day or date.today(),
    ).amount


def parse_amount_kzt(text: str) -> int | None:
    if not text:
        return None
    match = _AMOUNT_PATTERN.search(text)
    if not match:
        return None
    digits = re.sub(r"[\s ]", "", match.group(1)).replace(",", ".")
    try:
        value = Decimal(digits)
    except Exception:
        return None
    return _round_tenge(value) if value > 0 else None


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
        r"(?is)\b(?:истец|заявитель)\s*:\s*(.{1,500}?)(?=\b(?:ответчик|должник|взыскатель|кредитор)\s*:|$)",
        case_context,
    )
    if match:
        return match.group(1).strip()
    parenthetical = _PAREN_CLAIMANT_RE.search(case_context)
    return parenthetical.group(1).strip() if parenthetical else ""


def _claimant_has_iin_elsewhere(case_context: str, segment: str) -> bool:
    name_match = _PERSON_NAME_RE.search(segment or "")
    if not name_match:
        return False
    name = name_match.group(0)
    return bool(re.search(re.escape(name) + r".{0,80}\bИИН\s*" + r"\d{12}\b", case_context, re.IGNORECASE | re.DOTALL))


def claimant_is_individual(case_context: str) -> bool | None:
    """Resolve claimant type without allowing respondent markers to leak in."""
    if not case_context:
        return None
    segment = _claimant_segment(case_context)
    if segment:
        lowered = f" {segment.lower()} "
        if any(marker in lowered for marker in _LEGAL_ENTITY_MARKERS):
            return False
        if any(marker in lowered for marker in _IP_MARKERS):
            return True
        if ("иин" in lowered and _IIN_RE.search(segment)) or _claimant_has_iin_elsewhere(case_context, segment):
            return True
        return None

    iins = _IIN_RE.findall(case_context)
    lowered_all = f" {case_context.lower()} "
    if len(iins) == 1 and not any(marker in lowered_all for marker in _LEGAL_ENTITY_MARKERS):
        return True
    return None


def _clean_requests(requests: Iterable[str]) -> list[str]:
    return [item for item in requests if item and not _STATE_DUTY_RE.search(item)]


def _claim_text(title: str, requests: Iterable[str]) -> str:
    return "\n".join([title or "", *_clean_requests(requests)]).lower()


def _is_consumer_claim(claim_text: str) -> bool:
    return "защит" in claim_text and "прав потребител" in claim_text


def _explicit_exemption_reason(claim_text: str) -> str | None:
    """Recognize only exemptions asserted by the finalized cause of action."""
    text = claim_text.lower()
    if "алимент" in text:
        return "иск о взыскании алиментов"
    if "заработн" in text and any(word in text for word in ("взыск", "оплат", "трудов")):
        return "требование работника о взыскании заработной платы/иное трудовое требование"
    if "возмещ" in text and "вред" in text and any(word in text for word in ("здоров", "увечь", "смерт", "кормиль")):
        return "иск о возмещении вреда, причиненного здоровью или смертью"
    if "материальн" in text and "ущерб" in text and "уголов" in text:
        return "иск о возмещении материального ущерба, причиненного уголовным правонарушением"
    return None


def _potential_identity_exemption(case_context: str) -> bool:
    claimant = _claimant_segment(case_context).lower()
    if not claimant:
        return False
    return any(marker in claimant for marker in (
        "лицо с инвалид", "инвалид", "ветеран", "кандас", "реабилитирован",
        "участник великой отечественной", "герой советского", "герой социалистического",
    ))


def _is_independent_non_property_request(request: str) -> bool:
    lowered = (request or "").lower()
    if any(marker in lowered for marker in _STRONG_NON_PROPERTY_MARKERS):
        return True
    if not any(marker in lowered for marker in _GENERIC_NON_PROPERTY_MARKERS):
        return False
    if parse_amount_kzt(request) is not None:
        return False
    return not any(marker in lowered for marker in _MONETARY_OBLIGATION_MARKERS)


def _has_independent_non_property_request(title: str, requests: Iterable[str]) -> bool:
    clean = _clean_requests(requests)
    if any(_is_independent_non_property_request(item) for item in clean):
        return True
    # Title fallback is used only when the draft has no usable prayer item.
    return not clean and any(marker in (title or "").lower() for marker in _STRONG_NON_PROPERTY_MARKERS)


def gosposhlina_line(
    case_context: str,
    price_of_claim: str,
    *,
    title: str = "",
    requests: Iterable[str] = (),
    day: date | None = None,
    rates: Rates | None = None,
) -> str:
    """Return a court-facing duty line for common civil claims, fail-closed."""
    on = day or date.today()
    config = _config(rates)
    try:
        config.ensure_duty_valid_on(on)
    except RateUnavailable:
        return NEEDS_CALCULATION_MARKER

    is_individual = claimant_is_individual(case_context)
    if is_individual is None:
        return NEEDS_CALCULATION_MARKER

    request_list = tuple(requests)
    text = _claim_text(title, request_list)

    # Classification is driven by the finalized claim, not arbitrary evidence
    # text, so a salary certificate or old divorce in the background cannot
    # change the tariff for an unrelated debt claim.
    if any(marker in text for marker in _AMBIGUOUS_CLASSIFICATION_MARKERS):
        return NEEDS_CALCULATION_MARKER
    if "моральн" in text and not all(word in text for word in ("чест", "достоин")):
        return NEEDS_CALCULATION_MARKER
    if _potential_identity_exemption(case_context):
        return NEEDS_CALCULATION_MARKER

    exemption = _explicit_exemption_reason(text)
    if exemption:
        return f"0 тенге (освобождение от уплаты: {exemption}; {config.duty_source})"

    amount = parse_amount_kzt(price_of_claim)

    if "расторж" in text and "брак" in text and "раздел" not in text:
        try:
            duty = _mrp(config.duty_divorce_mrp, rates=config, day=on)
        except RateUnavailable:
            return NEEDS_CALCULATION_MARKER
        return f"{format_kzt(duty)} ({config.duty_divorce_mrp:g} МРП; {config.duty_source})"

    non_property = _has_independent_non_property_request(title, request_list)
    if amount is None:
        if not non_property:
            return NEEDS_CALCULATION_MARKER
        try:
            duty = _mrp(config.duty_non_property_mrp, rates=config, day=on)
        except RateUnavailable:
            return NEEDS_CALCULATION_MARKER
        return (
            f"{format_kzt(duty)} ({config.duty_non_property_mrp:g} МРП "
            f"за иск неимущественного характера; {config.duty_source})"
        )

    try:
        property_result = state_duty(amount, is_individual=is_individual, rates=config, day=on)
    except RateUnavailable:
        return NEEDS_CALCULATION_MARKER
    total = property_result.amount
    cap_mrp = config.duty_individual_cap_mrp if is_individual else config.duty_legal_entity_cap_mrp
    detail = f"{property_result.rate:.0%} от цены иска, предел {cap_mrp:,} МРП".replace(",", " ")

    if non_property:
        try:
            non_property_duty = _mrp(config.duty_non_property_mrp, rates=config, day=on)
        except RateUnavailable:
            return NEEDS_CALCULATION_MARKER
        total += non_property_duty
        detail += (
            f" + {config.duty_non_property_mrp:g} МРП за самостоятельное неимущественное "
            f"требование ({format_kzt(non_property_duty)})"
        )

    if _is_consumer_claim(text) and is_individual:
        return (
            f"Уплата отсрочена до принятия решения судом; расчетная сумма {format_kzt(total)} "
            f"({detail}; {config.consumer_deferral_source}; {config.duty_source})"
        )

    return f"{format_kzt(total)} ({detail}; {config.duty_source})"


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
    amount = _round_tenge(
        Decimal(principal) * Decimal(str(rate)) / Decimal(100) * Decimal(days) / Decimal(DAYS_IN_YEAR)
    )
    return LatePaymentPenalty(principal, start, end, rate_date, days, rate, amount)


def late_penalty_line(penalty: LatePaymentPenalty | None) -> str:
    if penalty is None:
        return NEEDS_RATE_MARKER
    return (
        f"{format_kzt(penalty.amount)} за период {penalty.period()} "
        f"({penalty.days} дн.; базовая ставка НБ РК {penalty.rate_percent:g}% "
        f"на {penalty.rate_date.strftime('%d.%m.%Y')}; {ARTICLE_353_LABEL}): {penalty.formula()}"
    )
