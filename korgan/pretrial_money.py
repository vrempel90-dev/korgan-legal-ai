from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from zoneinfo import ZoneInfo

from korgan.contractual_penalty import ContractualPenaltyTerms, parse_contractual_penalty_terms
from korgan.legal_calc import (
    RATE_SOURCE_ARTICLE,
    calc_gosposhlina_claim,
    claimant_is_individual,
    format_kzt,
)

LOGGER = logging.getLogger(__name__)

DEFAULT_VOLUNTARY_DAYS = 10

_DATE_TOKEN = r"(?P<day>\d{1,2})[./-](?P<month>\d{1,2})[./-](?P<year>\d{4})"
_MONEY_RE = re.compile(
    r"(?<!\d)(?P<amount>\d[\d\s\u00a0]*(?:[.,]\d{1,2})?)\s*(?:тенге|теңге|тг\b|₸|kzt)",
    re.IGNORECASE,
)
_DATE_RE = re.compile(_DATE_TOKEN)
_TERM_PATTERNS = (
    re.compile(
        r"(?i)(?:срок(?:\s+исполнения|\s+оплаты)?|оплат\w*.{0,70}?в\s+течение)\D{0,35}"
        r"(?P<days>\d{1,3})\s*(?:календарн\w*\s+)?дн",
    ),
    re.compile(
        r"(?i)(?P<days>\d{1,3})\s*(?:календарн\w*\s+)?дн\w*.{0,70}?"
        r"(?:срок(?:\s+исполнения|\s+оплаты)?|оплат\w*)",
    ),
)
_EVENT_KEYWORDS = (
    "поставк", "передач", "получен", "приемк", "приёмк", "акт", "оказан", "выполнен",
)
_PRINCIPAL_POSITIVE = (
    "основн", "долг", "задолж", "стоимост", "цена договора", "сумма договора",
    "сумма поставк", "оплат", "аванс", "предоплат", "берешек", "борыш",
)
_PRINCIPAL_NEGATIVE = (
    "неустой", "пен", "штраф", "представител", "юрист", "госпошлин",
    "государственн", "расход",
)
_REP_RE = re.compile(
    r"(?i)(?:расход\w*.{0,100}(?:представител|юрист|юридическ)|"
    r"(?:представител|юрист|юридическ).{0,100}расход\w*)"
)
_DOC_DATE_PATTERNS = (
    re.compile(r"(?i)(?:дата\s+документа|по\s+состоянию\s+на|расч[её]т\s+на)\s*[:\-]?\s*" + _DATE_TOKEN),
    re.compile(r"(?i)(?:претензи\w*|талап\w*)\s+от\s*" + _DATE_TOKEN),
)


def _round_tenge(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _parse_date_match(match: re.Match[str]) -> date | None:
    try:
        return date(int(match.group("year")), int(match.group("month")), int(match.group("day")))
    except (TypeError, ValueError):
        return None


def _today_almaty() -> date:
    return datetime.now(ZoneInfo("Asia/Almaty")).date()


def document_date_from_context(case_context: str, *, fallback: date | None = None) -> date:
    text = str(case_context or "")
    for pattern in _DOC_DATE_PATTERNS:
        match = pattern.search(text)
        if match:
            parsed = _parse_date_match(match)
            if parsed:
                return parsed
    return fallback or _today_almaty()


def _amount_from_match(match: re.Match[str]) -> int:
    raw = re.sub(r"[\s\u00a0]", "", match.group("amount")).replace(",", ".")
    try:
        value = Decimal(raw)
    except Exception:
        return 0
    return _round_tenge(value) if value > 0 else 0


def principal_from_context(case_context: str) -> int | None:
    """Choose the source-grounded principal amount, never a penalty/cost amount."""
    text = str(case_context or "")
    candidates: list[tuple[int, int, int]] = []
    for match in _MONEY_RE.finditer(text):
        amount = _amount_from_match(match)
        if amount <= 0:
            continue
        left = max(0, match.start() - 130)
        right = min(len(text), match.end() + 130)
        window = text[left:right].lower()
        score = sum(3 for token in _PRINCIPAL_POSITIVE if token in window)
        score -= sum(5 for token in _PRINCIPAL_NEGATIVE if token in window)
        if re.search(r"(?i)(?:основн\w*\s+долг|задолженн\w*|сумм\w*\s+долг)", window):
            score += 10
        candidates.append((score, amount, match.start()))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1], -item[2]), reverse=True)
    score, amount, _ = candidates[0]
    return amount if score >= 0 else None


def representative_costs_from_context(case_context: str) -> int | None:
    text = str(case_context or "")
    for segment in re.split(r"(?<=[.!?])\s+|\n+", text):
        if not _REP_RE.search(segment):
            continue
        match = _MONEY_RE.search(segment)
        if match:
            amount = _amount_from_match(match)
            if amount > 0:
                return amount
    return None


def performance_term_days_from_context(case_context: str) -> int | None:
    text = str(case_context or "")
    for pattern in _TERM_PATTERNS:
        match = pattern.search(text)
        if match:
            try:
                days = int(match.group("days"))
            except (TypeError, ValueError):
                continue
            if 0 < days <= 366:
                return days
    return None


def performance_event_date_from_context(case_context: str) -> date | None:
    """Find the date that starts the contractual performance term."""
    text = str(case_context or "")
    candidates: list[tuple[int, date, int]] = []
    for match in _DATE_RE.finditer(text):
        parsed = _parse_date_match(match)
        if not parsed:
            continue
        window = text[max(0, match.start() - 110): min(len(text), match.end() + 110)].lower()
        score = sum(4 for token in _EVENT_KEYWORDS if token in window)
        if "претензи" in window or "талап" in window:
            score -= 12
        if "договор" in window and not any(token in window for token in _EVENT_KEYWORDS):
            score -= 3
        candidates.append((score, parsed, match.start()))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], -item[2]), reverse=True)
    score, parsed, _ = candidates[0]
    return parsed if score > 0 else None


@dataclass(frozen=True, slots=True)
class PretrialPenaltyCalculation:
    base: int
    rate_percent_per_day: Decimal
    performance_event_date: date
    performance_term_days: int
    due_date: date
    delay_start: date
    document_date: date
    days: int
    amount_before_cap: int
    cap_percent: Decimal | None
    cap_amount: int | None
    cap_reached_on: date | None
    total: int
    contract_clause: str = ""

    def as_log_record(self) -> dict[str, Any]:
        rate = f"{self.rate_percent_per_day.normalize()}%/день"
        return {
            "база": self.base,
            "ставка": rate,
            "дата_начала_просрочки": self.delay_start.isoformat(),
            "дата_документа": self.document_date.isoformat(),
            "дней": self.days,
            "сумма_до_ограничителя": self.amount_before_cap,
            "ограничитель": self.cap_amount,
            "дата_достижения_ограничителя": self.cap_reached_on.isoformat() if self.cap_reached_on else None,
            "итог": self.total,
        }

    def prompt_block(self, *, language: str = "ru") -> str:
        cap_text = (
            f"{format_kzt(self.cap_amount)} ({self.cap_percent.normalize()}%)"
            if self.cap_amount is not None and self.cap_percent is not None
            else "не предусмотрен"
        )
        cap_date = self.cap_reached_on.strftime("%d.%m.%Y") if self.cap_reached_on else "не применимо"
        if language == "kk":
            return (
                "ДЕТЕРМИНИРОВАННЫЙ РАСЧЁТ KORGAN — ЧИСЛА НЕ ПЕРЕСЧИТЫВАТЬ МОДЕЛЬЮ:\n"
                f"база={self.base}; ставка={self.rate_percent_per_day.normalize()}%/күн; "
                f"мерзімнің соңғы күні={self.due_date:%d.%m.%Y}; "
                f"кешіктіру басталуы={self.delay_start:%d.%m.%Y}; "
                f"құжат күні={self.document_date:%d.%m.%Y}; күндер={self.days}; "
                f"шектеуге дейін={self.amount_before_cap}; шектеу={cap_text}; "
                f"шектеуге жету күні={cap_date}; қорытынды={self.total}."
            )
        return (
            "ДЕТЕРМИНИРОВАННЫЙ РАСЧЁТ KORGAN — МОДЕЛИ ЗАПРЕЩЕНО ПЕРЕСЧИТЫВАТЬ ЧИСЛА И ДАТЫ:\n"
            f"база={format_kzt(self.base)}; ставка={self.rate_percent_per_day.normalize()}% в день; "
            f"последний день срока={self.due_date:%d.%m.%Y}; "
            f"просрочка с={self.delay_start:%d.%m.%Y}; дата документа={self.document_date:%d.%m.%Y}; "
            f"дней={self.days}; сумма до ограничителя={format_kzt(self.amount_before_cap)}; "
            f"ограничитель={cap_text}; дата достижения ограничителя={cap_date}; "
            f"итог={format_kzt(self.total)}."
        )


@dataclass(frozen=True, slots=True)
class PretrialEconomics:
    current_due: int
    claim_price: int
    state_duty: int | None
    representative_costs: int | None
    litigation_total: int | None
    penalty_cap_reached: bool

    def line(self, *, language: str = "ru") -> str:
        duty = format_kzt(self.state_duty) if self.state_duty is not None else "[ДАННЫЕ: размер государственной пошлины]"
        rep = (
            format_kzt(self.representative_costs)
            if self.representative_costs is not None
            else "0 тенге (во входных данных расходы на представителя не заявлены и в расчет не включены)"
        )
        total = (
            format_kzt(self.litigation_total)
            if self.litigation_total is not None
            else "[ДАННЫЕ: итоговая сумма судебной экономики после подтверждения расходов]"
        )
        penalty_note = (
            "Ограничитель договорной неустойки достигнут; дальнейшее начисление не увеличивает требование."
            if self.penalty_cap_reached
            else "Неустойка учитывается только в рассчитанном на дату документа размере."
        )
        if language == "kk":
            return (
                "ДАУ ЭКОНОМИКАСЫ: қазір ерікті төлеуге "
                f"{format_kzt(self.current_due).replace(' тенге', ' теңге')}; сотқа жүгінгендегі талап қою бағасы "
                f"{format_kzt(self.claim_price).replace(' тенге', ' теңге')}; мемлекеттік баж {duty}; "
                f"өкіл шығыстары {rep}; ықтимал жиынтық {total}. {penalty_note}"
            )
        return (
            "ЭКОНОМИКА СПОРА: к добровольной оплате сейчас "
            f"{format_kzt(self.current_due)}; цена имущественного иска {format_kzt(self.claim_price)}; "
            f"государственная пошлина {duty}; расходы на представителя {rep}; "
            f"потенциальная сумма при судебном разбирательстве {total}. {penalty_note}"
        )


def calc_pretrial_penalty(
    *,
    principal: int,
    performance_event_date: date,
    performance_term_days: int,
    terms: ContractualPenaltyTerms,
    document_date: date,
) -> PretrialPenaltyCalculation:
    """Calculate penalty under the Article 173 next-day term-counting rule."""
    if principal <= 0:
        raise ValueError("Сумма долга должна быть положительной")
    if performance_term_days <= 0:
        raise ValueError("Срок исполнения должен быть положительным")
    if document_date < performance_event_date:
        raise ValueError("Дата документа не может быть раньше события исполнения")
    rate = Decimal(str(terms.rate_percent_per_day))
    if rate <= 0:
        raise ValueError("Ставка неустойки должна быть положительной")

    # Article 173 RK CC: the term starts on the day after the calendar event.
    # For N calendar days, event_date + N is the last performance day.
    due_date = performance_event_date + timedelta(days=performance_term_days)
    delay_start = due_date + timedelta(days=1)
    days = max(0, (document_date - delay_start).days + 1)
    raw = Decimal(principal) * rate / Decimal("100") * Decimal(days)
    amount_before_cap = _round_tenge(raw)

    cap_percent = Decimal(str(terms.cap_percent)) if terms.cap_percent is not None else None
    cap_amount: int | None = None
    cap_reached_on: date | None = None
    total = amount_before_cap
    if cap_percent is not None:
        if cap_percent <= 0:
            raise ValueError("Ограничитель неустойки должен быть положительным")
        cap_amount = _round_tenge(Decimal(principal) * cap_percent / Decimal("100"))
        daily_amount = Decimal(principal) * rate / Decimal("100")
        if daily_amount > 0:
            days_to_cap = int(math.ceil(Decimal(cap_amount) / daily_amount))
            cap_reached_on = delay_start + timedelta(days=max(days_to_cap - 1, 0))
        total = min(amount_before_cap, cap_amount)

    return PretrialPenaltyCalculation(
        base=principal,
        rate_percent_per_day=rate,
        performance_event_date=performance_event_date,
        performance_term_days=performance_term_days,
        due_date=due_date,
        delay_start=delay_start,
        document_date=document_date,
        days=days,
        amount_before_cap=amount_before_cap,
        cap_percent=cap_percent,
        cap_amount=cap_amount,
        cap_reached_on=cap_reached_on,
        total=total,
        contract_clause=terms.clause,
    )


def calculation_from_context(
    case_context: str,
    *,
    document_date: date | None = None,
) -> PretrialPenaltyCalculation | None:
    terms = parse_contractual_penalty_terms(case_context)
    if terms is None:
        return None
    principal = principal_from_context(case_context)
    event_date = performance_event_date_from_context(case_context)
    term_days = performance_term_days_from_context(case_context)
    if principal is None or event_date is None or term_days is None:
        return None
    doc_date = document_date or document_date_from_context(case_context)
    calculation = calc_pretrial_penalty(
        principal=principal,
        performance_event_date=event_date,
        performance_term_days=term_days,
        terms=terms,
        document_date=doc_date,
    )
    LOGGER.info(
        "PRETRIAL_MONEY_CALC %s",
        json.dumps(calculation.as_log_record(), ensure_ascii=False, sort_keys=True),
    )
    return calculation


def economics_from_context(
    case_context: str,
    calculation: PretrialPenaltyCalculation | None,
) -> PretrialEconomics | None:
    principal = calculation.base if calculation is not None else principal_from_context(case_context)
    if principal is None or principal <= 0:
        return None
    penalty = calculation.total if calculation is not None else 0
    claim_price = principal + penalty
    party_type = claimant_is_individual(case_context)
    state_duty = None if party_type is None else calc_gosposhlina_claim(claim_price, party_type)
    rep = representative_costs_from_context(case_context)
    rep_for_total = rep or 0
    litigation_total = claim_price + state_duty + rep_for_total if state_duty is not None else None
    return PretrialEconomics(
        current_due=claim_price,
        claim_price=claim_price,
        state_duty=state_duty,
        representative_costs=rep,
        litigation_total=litigation_total,
        penalty_cap_reached=bool(
            calculation
            and calculation.cap_amount is not None
            and calculation.total >= calculation.cap_amount
        ),
    )


def deterministic_money_context(
    case_context: str,
    *,
    calculation: PretrialPenaltyCalculation | None,
    economics: PretrialEconomics | None,
    language: str = "ru",
) -> str:
    lines = [
        "СИСТЕМНЫЕ ДЕТЕРМИНИРОВАННЫЕ ДАННЫЕ KORGAN. Это вычисленные значения, а не новые факты.",
        "Языковая модель не выполняет арифметику и не выбирает даты; она только формулирует текст вокруг этих значений.",
    ]
    if calculation is not None:
        lines.append(calculation.prompt_block(language=language))
    elif parse_contractual_penalty_terms(case_context) is not None:
        missing: list[str] = []
        if principal_from_context(case_context) is None:
            missing.append("сумма основного долга")
        if performance_event_date_from_context(case_context) is None:
            missing.append("дата события, от которого исчисляется срок исполнения")
        if performance_term_days_from_context(case_context) is None:
            missing.append("договорный срок исполнения в календарных днях")
        lines.append(
            "[ДАННЫЕ: для расчёта договорной неустойки не хватает: "
            + ", ".join(missing or ["исходные данные"])
            + "]"
        )
    if economics is not None:
        lines.append(economics.line(language=language))
        lines.append(f"Источник ставки государственной пошлины: {RATE_SOURCE_ARTICLE}.")
    return "\n".join(lines)
