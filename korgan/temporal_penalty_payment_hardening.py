from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from korgan.contractual_penalty import (
    TemporalPenaltyResult,
    calc_temporal_contractual_penalty,
    parse_contractual_penalty_terms,
)
from korgan.legal_calc import format_kzt
from korgan.legal_types import ClaimDraft, LegalResearch

LOGGER = logging.getLogger(__name__)
_INSTALLED = False

_DATE_TOKEN = r"\d{1,2}[./-]\d{1,2}[./-]\d{4}"
_MONEY_TOKEN = r"\d[\d\s\u00a0]*(?:[.,]\d{1,2})?"
_MONEY_RE = re.compile(rf"(?<!\d)({_MONEY_TOKEN})\s*(?:тенге|теңге|тг\b|₸)", re.IGNORECASE)
_PENALTY_RE = re.compile(r"(?i)(?:договорн\w*\s+неустойк\w*|неустойк\w*|пен[яию]\b|өсімпұл\w*|тұрақсыздық\s+айыб\w*)")
_PENALTY_DEMAND_SIGNAL_RE = re.compile(
    r"(?is)(?:(?:треб\w*|взыск\w*|уплат\w*|прос\w*).{0,120}(?:неустойк\w*|пен[яию]\b)|"
    r"(?:неустойк\w*|пен[яию]\b).{0,120}(?:треб\w*|взыск\w*|уплат\w*|подлеж\w*))"
)
_MONEY_DEMAND_RE = re.compile(r"(?i)(?:взыск\w*|уплат\w*|перечисл\w*|погас\w*|возмест\w*|треб\w*)")
_FORBIDDEN_PENALTY_PHRASES = (
    re.compile(r"(?i)подлеж\w*\s+уточнен\w*"),
    re.compile(r"(?i)прос\w*\s+произвести\s+расч[её]т"),
    re.compile(r"(?i)в\s+размере\s*,?\s*подлежащ\w*\s+начислен\w*"),
    re.compile(r"(?i)сумм\w*\s+подлеж\w*\s+уточнен\w*"),
)
_TRANSFER_RE = re.compile(
    r"(?i)(?:перечисл\w*|оплат\w*).{0,100}(?:расч[её]тн\w*\s+сч[её]т|банковск\w*\s+сч[её]т|ИИК\b|IBAN\b)"
)
_BANK_MARKER = "[ДАННЫЕ: банковские реквизиты для перечисления — ИИК, банк, БИК, КБе]"
_IBAN_RE = re.compile(r"(?i)(?:ИИК|IBAN)\s*[:№-]?\s*(KZ[0-9A-Z]{13,30})")
_BIC_RE = re.compile(r"(?i)БИК\s*[:№-]?\s*([A-Z0-9]{8,11})")
_KBE_RE = re.compile(r"(?i)КБе\s*[:№-]?\s*(\d{1,3})")
_BIN_RE = re.compile(r"(?i)БИН\s*[:№-]?\s*(\d{12})")
_NAME_RE = re.compile(r"(?i)(?:ТОО|АО)\s*[«\"]([^»\"]+)[»\"]")
_BANK_RE = re.compile(r"(?im)^.*?\bбанк\b[^\n;]{0,100}$")
_PURPOSE_RE = re.compile(r"(?im)(?:назначение\s+платежа|төлем\s+мақсаты)\s*[:\-]?\s*([^\n;]+)")
_EXPLICIT_DUE_PATTERNS = (
    re.compile(
        rf"(?is)(?:крайн\w*\s+(?:дата|срок)\s+(?:оплат\w*|исполнен\w*)|"
        rf"срок\s+(?:оплат\w*|исполнен\w*)[^\n.]{{0,80}}|оплат\w*\s+до)"
        rf"[^\d]{{0,80}}(?P<date>{_DATE_TOKEN})"
    ),
    re.compile(rf"(?is)(?:до|не\s+позднее)\s+(?P<date>{_DATE_TOKEN})[^\n.]{{0,80}}(?:оплат\w*|исполн\w*)"),
)
_AS_OF_RE = re.compile(
    rf"(?is)(?:по\s+состоянию\s+на|на\s+дату\s+документ\w*|дата\s+документ\w*\s*[:\-]?)\s*(?P<date>{_DATE_TOKEN})"
)
_TERM_DAYS_RE = re.compile(
    r"(?is)срок\s+оплат\w*[^\n.]{0,100}?(?P<days>\d{1,3})\s+календарн\w*\s+дн\w*"
)
_EVENT_PATTERNS = (
    re.compile(rf"(?is)(?:поставк\w*|передач\w*\s+товар\w*|товар\w*\s+(?:поставлен|передан)\w*)[^\d]{{0,60}}(?P<date>{_DATE_TOKEN})"),
    re.compile(rf"(?is)(?P<date>{_DATE_TOKEN})[^\n.]{{0,60}}(?:поставк\w*|товар\w*\s+(?:поставлен|передан)\w*)"),
)


class TemporalPenaltyReleaseError(RuntimeError):
    pass


def _parse_date(value: str) -> date | None:
    raw = str(value or "").strip().replace("/", ".").replace("-", ".")
    try:
        return datetime.strptime(raw, "%d.%m.%Y").date()
    except ValueError:
        return None


def _money(value: str) -> int:
    raw = re.sub(r"[\s\u00a0]", "", str(value or "")).replace(",", ".")
    try:
        return round(float(raw))
    except ValueError:
        return 0


def due_date_from_context(case_context: str) -> date | None:
    text = str(case_context or "")
    for pattern in _EXPLICIT_DUE_PATTERNS:
        match = pattern.search(text)
        if match:
            parsed = _parse_date(match.group("date"))
            if parsed is not None:
                return parsed

    term = _TERM_DAYS_RE.search(text)
    if not term:
        return None
    days = int(term.group("days"))
    if days <= 0:
        return None
    for pattern in _EVENT_PATTERNS:
        event = pattern.search(text)
        if event:
            event_date = _parse_date(event.group("date"))
            if event_date is not None:
                # Article 173 convention: counting starts on the next day; the
                # last day of an N-calendar-day term is event_date + N days.
                return event_date + timedelta(days=days)
    return None


def as_of_date_from_context(case_context: str) -> date:
    match = _AS_OF_RE.search(str(case_context or ""))
    if match:
        parsed = _parse_date(match.group("date"))
        if parsed is not None:
            return parsed
    return datetime.now(ZoneInfo("Asia/Almaty")).date()


def base_amount_from_context(case_context: str) -> int | None:
    text = str(case_context or "")
    candidates: list[tuple[int, int, int]] = []
    for index, match in enumerate(_MONEY_RE.finditer(text)):
        amount = _money(match.group(1))
        if amount <= 0:
            continue
        around = text[max(0, match.start() - 100): min(len(text), match.end() + 100)].casefold()
        score = 0
        if re.search(r"стоимост\w*.{0,40}(?:товар|услуг|работ)|сумм\w*\s+договор\w*", around):
            score += 30
        if re.search(r"основн\w*\s+долг|задолженн|сумм\w*\s+обязательств", around):
            score += 15
        if re.search(r"остат\w*.{0,30}(?:долг|задолж)", around):
            score -= 4
        if re.search(r"неустой|пен[яию]\b|штраф|госпошлин|представител", around):
            score -= 25
        candidates.append((score, -index, amount))
    if not candidates:
        return None
    score, _order, amount = max(candidates)
    return amount if score > 0 else None


def payments_from_context(case_context: str) -> list[tuple[date, int]]:
    result: list[tuple[date, int]] = []
    seen: set[tuple[date, int]] = set()
    for segment in re.split(r"(?<=[.!?])\s+|\n+", str(case_context or "")):
        if not re.search(r"(?i)(?:частичн\w*\s+оплат\w*|оплачен\w*|плат[её]ж\w*)", segment):
            continue
        dates = [_parse_date(match.group(0)) for match in re.finditer(_DATE_TOKEN, segment)]
        dates = [item for item in dates if item is not None]
        amounts = [_money(match.group(1)) for match in _MONEY_RE.finditer(segment)]
        amounts = [item for item in amounts if item > 0]
        if len(dates) != 1 or len(amounts) != 1:
            continue
        pair = (dates[0], amounts[0])
        if pair not in seen:
            seen.add(pair)
            result.append(pair)
    return sorted(result, key=lambda item: item[0])


def calculate_temporal_penalty_from_context(
    case_context: str,
    *,
    payment_allocation: str = "principal",
) -> TemporalPenaltyResult | None:
    text = str(case_context or "")
    if not _PENALTY_DEMAND_SIGNAL_RE.search(text):
        return None
    terms = parse_contractual_penalty_terms(text)
    if terms is None:
        return None
    base = base_amount_from_context(text)
    due = due_date_from_context(text)
    if base is None or due is None:
        return None
    result = calc_temporal_contractual_penalty(
        base_amount=base,
        due_date=due,
        rate_percent_per_day=terms.rate_percent_per_day,
        cap_percent=terms.cap_percent,
        payments=payments_from_context(text),
        as_of_date=as_of_date_from_context(text),
        payment_allocation=payment_allocation,
    )
    LOGGER.info(
        "TEMPORAL_PENALTY_CALC base=%s due_date=%s delay_start=%s as_of=%s segments=%s total_before_cap=%s cap_amount=%s cap_reached_date=%s total=%s daily_after=%s outstanding_principal=%s convention=%s",
        base,
        due.isoformat(),
        (due + timedelta(days=1)).isoformat(),
        as_of_date_from_context(text).isoformat(),
        result.segments,
        result.total_before_cap,
        result.cap_amount,
        result.cap_reached_date.isoformat() if result.cap_reached_date else None,
        result.total,
        result.daily_after,
        result.outstanding_principal,
        result.convention,
    )
    return result


def _fmt_date(value: date) -> str:
    return value.strftime("%d.%m.%Y")


def render_penalty_calculation(result: TemporalPenaltyResult, *, language: str = "ru") -> list[str]:
    if result.total is None:
        return []
    lines: list[str] = []
    if language == "kk":
        lines.append("Шарттық тұрақсыздық айыбын детерминирленген есептеу:")
    else:
        lines.append("Детерминированный расчёт договорной неустойки:")
    for index, segment in enumerate(result.segments, start=1):
        base = format_kzt(int(segment["base"]))
        daily = format_kzt(int(segment["rate_per_day"]))
        amount = format_kzt(int(segment["amount"]))
        rate_text = _rate_percent_for_segment(result, segment)
        lines.append(
            f"{index}) {_fmt_date(segment['from'])}–{_fmt_date(segment['to'])}: база {base}; "
            f"ставка {rate_text}% в день; {daily}/день × {segment['days']} календарных дней = {amount}."
        )
    total_before = format_kzt(result.total_before_cap or 0)
    total = format_kzt(result.total)
    if result.cap_amount is not None:
        cap = format_kzt(result.cap_amount)
        reached = _fmt_date(result.cap_reached_date) if result.cap_reached_date else "не достигнут"
        lines.append(
            f"Сумма до ограничителя: {total_before}. Договорный ограничитель: {cap}; "
            f"дата достижения ограничителя: {reached}. Итог на дату расчёта: {total}."
        )
    else:
        lines.append(f"Итого договорная неустойка на дату расчёта: {total}.")
    if result.daily_after:
        lines.append(f"Текущее ежедневное начисление после даты расчёта: {format_kzt(result.daily_after)} в день.")
    else:
        lines.append("Текущее ежедневное начисление после даты расчёта: 0 тенге; договорный ограничитель достигнут.")
    lines.append(
        "Соглашения расчёта: просрочка начинается со дня, следующего за последним днём срока исполнения; "
        "календарные дни в каждом сегменте считаются включительно; в день частичной оплаты неустойка начисляется "
        "на прежнюю базу, платёж уменьшает основной долг со следующего календарного дня; платежи отнесены на основной долг."
    )
    return lines


def _rate_percent_for_segment(result: TemporalPenaltyResult, segment: dict[str, object]) -> str:
    base = int(segment["base"])
    daily = int(segment["rate_per_day"])
    if base <= 0:
        return "0"
    value = daily * 100 / base
    return f"{value:g}".replace(".", ",")


def augment_case_context(case_context: str, result: TemporalPenaltyResult | None) -> str:
    if result is None or result.total is None:
        return case_context
    lines = render_penalty_calculation(result)
    block = [
        "ДЕТЕРМИНИРОВАННЫЕ ДАННЫЕ KORGAN — модель не пересчитывает суммы и даты:",
        f"ТРЕБОВАНИЕ ИЗ ДОКУМЕНТА: уплатить договорную неустойку в размере {format_kzt(result.total)}.",
        *lines,
    ]
    return f"{case_context.rstrip()}\n\n" + "\n".join(block)


def _canonical_penalty_demand(result: TemporalPenaltyResult, language: str) -> str:
    amount = format_kzt(result.total or 0)
    as_of = result.segments[-1]["to"] if result.segments else None
    date_text = _fmt_date(as_of) if isinstance(as_of, date) else "дату документа"
    if language == "kk":
        return f"Шарттық тұрақсыздық айыбын {date_text} жағдай бойынша {amount.replace(' тенге', ' теңге')} мөлшерінде төлеу."
    return f"Уплатить договорную неустойку по состоянию на {date_text} в размере {amount}."


def apply_penalty_result_to_draft(draft: Any, result: TemporalPenaltyResult | None, *, language: str = "ru") -> bool:
    if result is None or result.total is None:
        return False
    attr = "requests" if hasattr(draft, "requests") else "demands" if hasattr(draft, "demands") else ""
    if not attr:
        return False
    demands = list(getattr(draft, attr) or [])
    canonical = _canonical_penalty_demand(result, language)
    penalty_indices = [index for index, value in enumerate(demands) if _PENALTY_RE.search(str(value))]
    changed = False
    if penalty_indices:
        first = penalty_indices[0]
        if demands[first] != canonical:
            demands[first] = canonical
            changed = True
    else:
        demands.append(canonical)
        changed = True
    setattr(draft, attr, demands)

    facts = list(getattr(draft, "facts", []) or [])
    calculation = render_penalty_calculation(result, language=language)
    if calculation and not any("Детерминированный расчёт договорной неустойки" in str(item) for item in facts):
        facts.extend(calculation)
        draft.facts = facts
        changed = True
    return changed


def _document_lines(draft: Any) -> list[str]:
    result: list[str] = []
    for attr in (
        "title", "sender", "recipient", "claimant", "defendant", "facts", "legal_basis",
        "demands", "requests", "deadline", "consequences", "attachments",
    ):
        value = getattr(draft, attr, None)
        if isinstance(value, list):
            result.extend(str(item) for item in value if str(item).strip())
        elif value:
            result.append(str(value))
    return result


def _bank_complete(text: str) -> bool:
    upper = text.upper()
    return bool(
        _IBAN_RE.search(text)
        and _BIC_RE.search(text)
        and _KBE_RE.search(text)
        and "БАНК" in upper
        and _BIN_RE.search(text)
        and ("НАЗНАЧЕНИЕ ПЛАТЕЖА" in upper or "ТӨЛЕМ МАҚСАТЫ" in upper)
    )


def _bank_requisites_from_source(case_context: str) -> str:
    text = str(case_context or "")
    iban = _IBAN_RE.search(text)
    bic = _BIC_RE.search(text)
    kbe = _KBE_RE.search(text)
    bank = _BANK_RE.search(text)
    bin_match = _BIN_RE.search(text)
    name = _NAME_RE.search(text)
    purpose = _PURPOSE_RE.search(text)
    if not (iban and bic and kbe and bank):
        return _BANK_MARKER
    recipient = f"ТОО «{name.group(1)}»" if name else "[ДАННЫЕ: наименование получателя]"
    bin_text = bin_match.group(1) if bin_match else "[ДАННЫЕ: БИН получателя]"
    bank_text = " ".join(bank.group(0).split()).strip(" ;")
    purpose_text = purpose.group(1).strip() if purpose else "[ДАННЫЕ: назначение платежа]"
    return (
        f"Банковские реквизиты получателя: {recipient}; БИН: {bin_text}; ИИК: {iban.group(1)}; "
        f"Банк: {bank_text}; БИК: {bic.group(1)}; КБе: {kbe.group(1)}; Назначение платежа: {purpose_text}."
    )


def ensure_payment_requisites(draft: Any, case_context: str) -> bool:
    text = "\n".join(_document_lines(draft))
    if not _TRANSFER_RE.search(text):
        return False
    if _BANK_MARKER in text or _bank_complete(text):
        return False
    line = _bank_requisites_from_source(case_context)
    attr = "demands" if hasattr(draft, "demands") else "facts" if hasattr(draft, "facts") else ""
    if not attr:
        return False
    values = list(getattr(draft, attr) or [])
    if line not in values:
        values.append(line)
        setattr(draft, attr, values)
        LOGGER.info("PAYMENT_REQUISITES_ENFORCED marker=%s", line == _BANK_MARKER)
        return True
    return False


def penalty_demand_issues(draft: Any) -> list[str]:
    demands = list(getattr(draft, "requests", []) or getattr(draft, "demands", []) or [])
    issues: list[str] = []
    for value in demands:
        text = str(value)
        if not (_PENALTY_RE.search(text) and _MONEY_DEMAND_RE.search(text)):
            continue
        if any(pattern.search(text) for pattern in _FORBIDDEN_PENALTY_PHRASES):
            issues.append("денежное требование о неустойке оставлено без числового расчёта")
        if not _MONEY_RE.search(text):
            issues.append("денежное требование о неустойке не содержит конкретной суммы")
    return list(dict.fromkeys(issues))


def payment_requisites_issues(draft: Any) -> list[str]:
    text = "\n".join(_document_lines(draft))
    if not _TRANSFER_RE.search(text):
        return []
    if _BANK_MARKER in text or _bank_complete(text):
        return []
    return ["требование перечислить деньги на счёт не содержит банковских реквизитов или [ДАННЫЕ]-маркера"]


def narrow_release_issues(draft: Any) -> list[str]:
    return [*penalty_demand_issues(draft), *payment_requisites_issues(draft)]


def _enforce_or_raise(draft: Any, case_context: str, result: TemporalPenaltyResult | None, language: str) -> bool:
    changed = apply_penalty_result_to_draft(draft, result, language=language)
    changed = ensure_payment_requisites(draft, case_context) or changed
    issues = narrow_release_issues(draft)
    if issues:
        LOGGER.error("TEMPORAL_PENALTY_PAYMENT_RELEASE_BLOCKED issues=%s", issues)
        raise TemporalPenaltyReleaseError("; ".join(issues))
    return changed


def install_temporal_penalty_payment_hardening() -> None:
    """Layer deterministic money/requisites over existing model stages.

    No structured-response call is introduced here. The wrappers call the
    already-installed claim/pretrial methods exactly once and only enrich their
    input/output deterministically.
    """
    global _INSTALLED
    if _INSTALLED:
        return

    from korgan.claim_state_duty import apply_professional_state_duty
    from korgan.pretrial import PretrialProductionService
    from korgan.professional_claim_finalizer import _recalculate_price
    from korgan.stable_legal_release import StableLegalProductionService

    current_pretrial = PretrialProductionService.draft_pretrial

    async def pretrial_with_temporal_money(
        self: PretrialProductionService,
        case_context: str,
        research: LegalResearch,
        language: str = "ru",
    ):
        result = calculate_temporal_penalty_from_context(case_context)
        enriched = augment_case_context(case_context, result)
        draft = await current_pretrial(self, enriched, research, language=language)
        _enforce_or_raise(draft, case_context, result, language)
        return draft

    PretrialProductionService.draft_pretrial = pretrial_with_temporal_money  # type: ignore[assignment]

    current_claim = StableLegalProductionService.draft_claim

    async def claim_with_temporal_money(
        self: StableLegalProductionService,
        case_context: str,
        research: LegalResearch,
        language: str = "ru",
    ) -> ClaimDraft:
        result = calculate_temporal_penalty_from_context(case_context)
        enriched = augment_case_context(case_context, result)
        draft = await current_claim(self, enriched, research, language=language)
        changed = _enforce_or_raise(draft, case_context, result, language)
        if changed and result is not None and result.total is not None:
            _recalculate_price(draft)
            apply_professional_state_duty(case_context, research, draft)
        return draft

    StableLegalProductionService.draft_claim = claim_with_temporal_money  # type: ignore[assignment]
    _INSTALLED = True
    LOGGER.info("Installed temporal penalty + payment requisites hardening; no extra model round")
