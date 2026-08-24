"""Deterministic legal arithmetic for KORGAN.

Anything computable from a verified legal rate belongs here, not in a model
prompt. The model may not invent, round or "remember" these numbers.

Court-duty constants below are intentionally year-bound.  The calculator fails
closed outside 2026 so a new budget law / Tax Code amendment cannot silently
turn into a wrong amount in a court filing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable

RATE_SOURCE_ARTICLE = "статья 665 Налогового кодекса РК (Кодекс РК № 214-VIII)"
RATE_SOURCE_URL = "https://adilet.zan.kz/rus/docs/K2500000214"
MRP_SOURCE_URL = "https://adilet.zan.kz/rus/docs/Z2500000239"
GPK_ARTICLE_106_URL = "https://adilet.zan.kz/rus/docs/K1500000377"
MRP_2026 = 4325
RATE_INDIVIDUAL = 0.01
RATE_LEGAL_ENTITY = 0.03
CAP_MRP = 10_000
CAP_MRP_LEGAL_ENTITY = 20_000
NON_PROPERTY_MRP = Decimal("0.5")
DIVORCE_MRP = Decimal("0.3")
STATE_DUTY_VALID_FROM = date(2026, 1, 1)
STATE_DUTY_VALID_THROUGH = date(2026, 12, 31)
NEEDS_CALCULATION_MARKER = "[ТРЕБУЕТ РАСЧЁТА ГОСПОШЛИНЫ]"

# Ordinary civil property claims distinguish physical and legal persons.  An
# individual entrepreneur is still a physical person; IP-specific rates exist
# only for special categories expressly named by article 665 (for example tax
# audit-notice challenges), which this civil-claim helper does not guess.
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

# Categories that are safe to recognize from the actual claim wording.  More
# complicated categories deliberately return NEEDS_CALCULATION_MARKER rather
# than applying a plausible-looking but potentially wrong tariff.
_NON_PROPERTY_REQUEST_MARKERS = (
    "расторгнуть договор",
    "обязать ответчика",
    "обязать ",
    "выселить",
    "вселить",
    "освободить имущество от ареста",
    "продлить срок принятия наследства",
    "изменить договор найма",
    "расторгнуть договор найма",
)
_AMBIGUOUS_CLASSIFICATION_MARKERS = (
    "признать сделку недействитель",
    "признать договор недействитель",
    "признать право собственности",
)


def _round_tenge(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _mrp(multiplier: Decimal | float | int) -> int:
    return _round_tenge(Decimal(MRP_2026) * Decimal(str(multiplier)))


def calc_gosposhlina_claim(amount: int, is_individual: bool) -> int:
    """State duty for an ordinary property claim under art. 665(1)(1), 2026.

    Physical persons: 1%, capped at 10,000 MRP.
    Legal persons: 3%, capped at 20,000 MRP.
    """
    if amount < 0:
        raise ValueError("Сумма иска не может быть отрицательной")
    rate = RATE_INDIVIDUAL if is_individual else RATE_LEGAL_ENTITY
    cap_mrp = CAP_MRP if is_individual else CAP_MRP_LEGAL_ENTITY
    raw = _round_tenge(Decimal(amount) * Decimal(str(rate)))
    return min(raw, cap_mrp * MRP_2026)


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


def _claim_text(title: str, requests: Iterable[str]) -> str:
    clean_requests = [item for item in requests if not _STATE_DUTY_RE.search(item or "")]
    return "\n".join([title or "", *clean_requests]).lower()


def _is_consumer_claim(case_context: str, claim_text: str) -> bool:
    text = f"{case_context}\n{claim_text}".lower()
    return "защит" in text and "прав потребител" in text


def _explicit_exemption_reason(case_context: str, claim_text: str) -> str | None:
    text = f"{case_context}\n{claim_text}".lower()
    # High-confidence claim-category exemptions from art. 668.  Identity-based
    # exemptions (disability, veteran status, etc.) are not inferred here unless
    # a dedicated verified intake field is added; guessing such status is worse
    # than returning NEEDS_CALCULATION_MARKER.
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


def _has_non_property_request(claim_text: str) -> bool:
    return any(marker in claim_text for marker in _NON_PROPERTY_REQUEST_MARKERS)


def gosposhlina_line(
    case_context: str,
    price_of_claim: str,
    *,
    title: str = "",
    requests: Iterable[str] = (),
    day: date | None = None,
) -> str:
    """Return a court-facing duty line for common civil claims, fail-closed.

    The function intentionally supports only classifications that can be made
    safely from the structured claim.  Special administrative/tax, bankruptcy,
    arbitration and other tariffs from art. 665 require a dedicated document
    route and therefore are not guessed by this civil-claim helper.
    """
    on = day or date.today()
    if on < STATE_DUTY_VALID_FROM or on > STATE_DUTY_VALID_THROUGH:
        return NEEDS_CALCULATION_MARKER

    is_individual = claimant_is_individual(case_context)
    if is_individual is None:
        return NEEDS_CALCULATION_MARKER

    text = _claim_text(title, requests)
    all_text = f"{case_context}\n{text}".lower()

    if any(marker in all_text for marker in _AMBIGUOUS_CLASSIFICATION_MARKERS):
        return NEEDS_CALCULATION_MARKER
    if "моральн" in all_text and not all(word in all_text for word in ("чест", "достоин")):
        return NEEDS_CALCULATION_MARKER
    if _potential_identity_exemption(case_context):
        return NEEDS_CALCULATION_MARKER

    exemption = _explicit_exemption_reason(case_context, text)
    if exemption:
        return f"0 тенге (освобождение от уплаты: {exemption}; статья 668 Налогового кодекса РК)"

    amount = parse_amount_kzt(price_of_claim)

    if "расторжен" in all_text and "брак" in all_text and "раздел" not in all_text:
        duty = _mrp(DIVORCE_MRP)
        return f"{format_kzt(duty)} (0,3 МРП; {RATE_SOURCE_ARTICLE})"

    non_property = _has_non_property_request(text)
    if amount is None:
        if not non_property:
            return NEEDS_CALCULATION_MARKER
        duty = _mrp(NON_PROPERTY_MRP)
        return f"{format_kzt(duty)} (0,5 МРП за иск неимущественного характера; {RATE_SOURCE_ARTICLE})"

    property_duty = calc_gosposhlina_claim(amount, is_individual)
    rate_label = "1%" if is_individual else "3%"
    cap_label = "10 000 МРП" if is_individual else "20 000 МРП"
    total = property_duty
    detail = f"{rate_label} от цены иска, предел {cap_label}"
    if non_property:
        non_property_duty = _mrp(NON_PROPERTY_MRP)
        total += non_property_duty
        detail += f" + 0,5 МРП за самостоятельное неимущественное требование ({format_kzt(non_property_duty)})"

    if _is_consumer_claim(case_context, text) and is_individual:
        return (
            f"Уплата отсрочена до принятия решения судом; расчетная сумма {format_kzt(total)} "
            f"({detail}; часть 3 статьи 106 ГПК РК; {RATE_SOURCE_ARTICLE})"
        )

    return f"{format_kzt(total)} ({detail}; {RATE_SOURCE_ARTICLE})"


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
