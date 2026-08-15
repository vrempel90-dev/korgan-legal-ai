from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation

from korgan_legal_ai.domain.models import LockedCase

_NUMBER_RE = re.compile(
    r"(?<![\w])[-+]?\d(?:[\d\s\u00a0\u202f]*\d)?(?:[.,]\d+)?(?![\w])"
)
_NON_WORD_RE = re.compile(r"[^0-9a-zа-яёәғқңөұүһі]+", re.IGNORECASE)

_MONTH_NAMES: dict[int, tuple[str, ...]] = {
    1: ("января", "январь", "қаңтар"),
    2: ("февраля", "февраль", "ақпан"),
    3: ("марта", "март", "наурыз"),
    4: ("апреля", "апрель", "сәуір"),
    5: ("мая", "май", "мамыр"),
    6: ("июня", "июнь", "маусым"),
    7: ("июля", "июль", "шілде"),
    8: ("августа", "август", "тамыз"),
    9: ("сентября", "сентябрь", "қыркүйек"),
    10: ("октября", "октябрь", "қазан"),
    11: ("ноября", "ноябрь", "қараша"),
    12: ("декабря", "декабрь", "желтоқсан"),
}


def _canonical_text(value: str) -> str:
    return " ".join(part for part in _NON_WORD_RE.sub(" ", value.lower()).split() if part)


def _decimal_token(value: str) -> Decimal | None:
    normalized = value.replace("\u00a0", "").replace("\u202f", "").replace(" ", "")
    normalized = normalized.replace(",", ".")
    try:
        return Decimal(normalized)
    except InvalidOperation:
        return None


def _numbers_in_source(raw_text: str) -> set[Decimal]:
    values: set[Decimal] = set()
    for match in _NUMBER_RE.finditer(raw_text):
        parsed = _decimal_token(match.group(0))
        if parsed is not None:
            values.add(parsed)
    return values


def _date_in_source(value: date, raw_text: str) -> bool:
    lower = raw_text.lower()
    direct = (
        value.isoformat(),
        value.strftime("%d.%m.%Y"),
        value.strftime("%d/%m/%Y"),
        f"{value.day}.{value.month}.{value.year}",
        f"{value.day}/{value.month}/{value.year}",
    )
    if any(candidate in lower for candidate in direct):
        return True

    for month_name in _MONTH_NAMES[value.month]:
        pattern = re.compile(
            rf"(?<!\d){value.day}\s+{re.escape(month_name)}\s+{value.year}(?!\d)",
            re.IGNORECASE,
        )
        if pattern.search(raw_text):
            return True
    return False


def _identifier_in_source(value: str, raw_text: str) -> bool:
    compact = re.sub(r"[\s\u00a0\u202f-]+", "", value)
    if not compact:
        return False
    pattern = "".join(re.escape(char) + r"[\s\u00a0\u202f-]*" for char in compact).rstrip("*")
    return re.search(pattern, raw_text) is not None


def validate_locked_case_grounding(raw_text: str, case: LockedCase) -> list[str]:
    """Verify critical typed values came from the supplied source text.

    Fact Lock is model-assisted extraction, so typed values get a second deterministic guard before
    routing. This does not decide meaning; it only rejects values that are absent from the actual
    user/document source. Calculated values intentionally do not belong here — they are produced
    later by CalculationLayer.
    """
    issues: list[str] = []
    canonical_source = _canonical_text(raw_text)
    source_numbers = _numbers_in_source(raw_text)

    for party in case.parties:
        party_name = _canonical_text(party.name)
        if party_name and party_name not in canonical_source:
            issues.append(
                f"Уточните наименование стороны: значение «{party.name}» не найдено в исходных данных."
            )
        if party.iin_bin and not _identifier_in_source(party.iin_bin, raw_text):
            issues.append("Уточните БИН/ИИН стороны: извлеченное значение не найдено в исходных данных.")
        if party.address:
            address = _canonical_text(party.address)
            if address and address not in canonical_source:
                issues.append("Уточните адрес стороны: извлеченное значение не найдено в исходных данных.")

    for fact in case.facts:
        if fact.event_date is not None and not _date_in_source(fact.event_date, raw_text):
            issues.append(
                f"Уточните дату факта {fact.id}: извлеченная дата отсутствует в исходных данных."
            )

    financial_fields = (
        ("contract_amount", case.financials.contract_amount),
        ("principal", case.financials.principal),
        ("penalty", case.financials.penalty),
        ("interest", case.financials.interest),
        ("other", case.financials.other),
        ("user_stated_total", case.financials.user_stated_total),
        ("penalty_rate_percent_per_day", case.financials.penalty_rate_percent_per_day),
        ("penalty_cap_percent_of_principal", case.financials.penalty_cap_percent_of_principal),
    )
    for field_name, value in financial_fields:
        if value is not None and value not in source_numbers:
            issues.append(
                f"Уточните {field_name}: извлеченное числовое значение отсутствует в исходных данных."
            )
    for index, payment in enumerate(case.financials.payments, start=1):
        if payment not in source_numbers:
            issues.append(
                f"Уточните payment {index}: извлеченная сумма отсутствует в исходных данных."
            )

    for field_name, value in (
        ("obligation_due_date", case.procedure.obligation_due_date),
        ("pretrial_demand_sent_date", case.procedure.pretrial_demand_sent_date),
    ):
        if value is not None and not _date_in_source(value, raw_text):
            issues.append(
                f"Уточните {field_name}: извлеченная дата отсутствует в исходных данных."
            )

    if case.procedure.representative_name:
        representative = _canonical_text(case.procedure.representative_name)
        if representative and representative not in canonical_source:
            issues.append(
                "Уточните имя подписанта/представителя: извлеченное значение отсутствует в исходных данных."
            )

    return list(dict.fromkeys(issues))
