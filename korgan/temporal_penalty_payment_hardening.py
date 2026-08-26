from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any
from zoneinfo import ZoneInfo

from korgan.contractual_penalty import TemporalPenaltyResult, calc_temporal_contractual_penalty, parse_contractual_penalty_terms
from korgan.legal_calc import format_kzt
from korgan.legal_types import ClaimDraft, LegalResearch

LOGGER = logging.getLogger(__name__)
_INSTALLED = False

_DATE = r"\d{1,2}[./-]\d{1,2}[./-]\d{4}"
_AMOUNT = r"\d[\d\s\u00a0]*(?:[.,]\d{1,2})?"
_MONEY_RE = re.compile(rf"(?<!\d)({_AMOUNT})\s*(?:тенге|теңге|тг\b|₸)", re.I)
_PENALTY_RE = re.compile(r"(?i)(?:договорн\w*\s+неустойк\w*|неустойк\w*|пен[яию]\b|өсімпұл\w*|тұрақсыздық\s+айыб\w*)")
_PENALTY_DEMAND_RE = re.compile(r"(?is)(?:(?:треб\w*|взыск\w*|уплат\w*|прос\w*).{0,120}(?:неустойк\w*|пен[яию]\b)|(?:неустойк\w*|пен[яию]\b).{0,120}(?:треб\w*|взыск\w*|уплат\w*|подлеж\w*))")
_MONEY_DEMAND_RE = re.compile(r"(?i)(?:взыск\w*|уплат\w*|перечисл\w*|погас\w*|возмест\w*|треб\w*)")
_FORBIDDEN = (
    re.compile(r"(?i)подлеж\w*\s+уточнен\w*"),
    re.compile(r"(?i)прос\w*\s+произвести\s+расч[её]т"),
    re.compile(r"(?i)в\s+размере\s*,?\s*подлежащ\w*\s+начислен\w*"),
    re.compile(r"(?i)сумм\w*\s+подлеж\w*\s+уточнен\w*"),
)
_TRANSFER_RE = re.compile(r"(?i)(?:перечисл\w*|оплат\w*).{0,100}(?:расч[её]тн\w*\s+сч[её]т|банковск\w*\s+сч[её]т|ИИК\b|IBAN\b)")
_TRANSFER_TAIL_RE = re.compile(r"(?is)((?:пут[её]м\s+)?перечисл\w*[^\n]*?(?:расч[её]тн\w*\s+сч[её]т|банковск\w*\s+сч[её]т|ИИК\b|IBAN\b)[^\n]*)")
_BANK_MARKER = "[ДАННЫЕ: банковские реквизиты для перечисления — ИИК, банк, БИК, КБе]"
_IBAN_RE = re.compile(r"(?i)(?:ИИК|IBAN)\s*[:№-]?\s*(KZ[0-9A-Z]{13,30})")
_BIC_RE = re.compile(r"(?i)БИК\s*[:№-]?\s*([A-Z0-9]{8,11})")
_KBE_RE = re.compile(r"(?i)КБе\s*[:№-]?\s*(\d{1,3})")
_BIN_RE = re.compile(r"(?i)БИН\s*[:№-]?\s*(\d{12})")
_NAME_RE = re.compile(r"(?i)((?:ТОО|АО)\s*[«\"][^»\"]+[»\"])")
_BANK_LINE_RE = re.compile(r"(?im)^\s*(?:Банк\s*:\s*)?([^\n;]*\bбанк\b[^\n;]*)$")
_PURPOSE_RE = re.compile(r"(?im)(?:назначение\s+платежа|төлем\s+мақсаты)\s*[:\-]?\s*([^\n;]+)")
_EXPLICIT_DUE_RE = re.compile(rf"(?is)(?:крайн\w*\s+(?:дата|срок)\s+(?:оплат\w*|исполнен\w*)|срок\s+(?:оплат\w*|исполнен\w*)|оплат\w*\s+до)[^\n]{{0,140}}?(?P<date>{_DATE})")
_DUE_BEFORE_ACTION_RE = re.compile(rf"(?is)(?:до|не\s+позднее)\s+(?P<date>{_DATE})[^\n.]{{0,80}}(?:оплат\w*|исполн\w*)")
_AS_OF_RE = re.compile(rf"(?is)(?:по\s+состоянию\s+на|на\s+дату\s+документ\w*|дата\s+документ\w*\s*[:\-]?|дата\s+претензи\w*\s*[:\-]?)\s*(?P<date>{_DATE})")
_TERM_DAYS_RE = re.compile(r"(?is)срок\s+оплат\w*[^\n.]{0,100}?(?P<days>\d{1,3})\s+календарн\w*\s+дн\w*")
_EVENT_RES = (
    re.compile(rf"(?is)(?:поставк\w*|передач\w*\s+товар\w*|товар\w*\s+(?:поставлен|передан)\w*)[^\d]{{0,60}}(?P<date>{_DATE})"),
    re.compile(rf"(?is)(?P<date>{_DATE})[^\n.]{{0,80}}(?:поставк\w*|товар\w*\s+(?:поставлен|передан)\w*)"),
)


class TemporalPenaltyReleaseError(RuntimeError):
    pass


def _parse_date(raw: str) -> date | None:
    value = str(raw or "").strip().replace("/", ".").replace("-", ".")
    try:
        return datetime.strptime(value, "%d.%m.%Y").date()
    except ValueError:
        return None


def _parse_money(raw: str) -> int:
    value = re.sub(r"[\s\u00a0]", "", str(raw or "")).replace(",", ".")
    try:
        parsed = Decimal(value)
    except (InvalidOperation, ValueError):
        return 0
    if not parsed.is_finite() or parsed <= 0:
        return 0
    return int(parsed.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def due_date_from_context(case_context: str) -> date | None:
    text = str(case_context or "")
    for pattern in (_EXPLICIT_DUE_RE, _DUE_BEFORE_ACTION_RE):
        match = pattern.search(text)
        if match:
            parsed = _parse_date(match.group("date"))
            if parsed:
                return parsed
    term = _TERM_DAYS_RE.search(text)
    if not term or int(term.group("days")) <= 0:
        return None
    for pattern in _EVENT_RES:
        match = pattern.search(text)
        if match:
            event_date = _parse_date(match.group("date"))
            if event_date:
                return event_date + timedelta(days=int(term.group("days")))
    return None


def as_of_date_from_context(case_context: str) -> date:
    match = _AS_OF_RE.search(str(case_context or ""))
    if match:
        parsed = _parse_date(match.group("date"))
        if parsed:
            return parsed
    return datetime.now(ZoneInfo("Asia/Almaty")).date()


def base_amount_from_context(case_context: str) -> int | None:
    text = str(case_context or "")
    candidates: list[tuple[int, int, int]] = []
    for index, match in enumerate(_MONEY_RE.finditer(text)):
        amount = _parse_money(match.group(1))
        if amount <= 0:
            continue
        around = text[max(0, match.start() - 85): min(len(text), match.end() + 85)].casefold()
        score = 0
        if re.search(r"(?:стоимост\w*.{0,45}(?:товар|услуг|работ)|(?:товар|услуг|работ)\w*.{0,45}стоимост\w*|сумм\w*\s+договор\w*)", around):
            score += 35
        if re.search(r"основн\w*\s+долг|задолженн|сумм\w*\s+обязательств", around):
            score += 15
        if re.search(r"остат\w*.{0,30}(?:долг|задолж)", around):
            score -= 8
        if re.search(r"неустой|пен[яию]\b|штраф|госпошлин|представител", around):
            score -= 20
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
        dates = [_parse_date(match.group(0)) for match in re.finditer(_DATE, segment)]
        dates = [item for item in dates if item]
        amounts = [_parse_money(match.group(1)) for match in _MONEY_RE.finditer(segment)]
        amounts = [item for item in amounts if item > 0]
        if len(dates) == 1 and len(amounts) == 1:
            pair = (dates[0], amounts[0])
            if pair not in seen:
                seen.add(pair)
                result.append(pair)
    return sorted(result, key=lambda item: item[0])


def calculate_temporal_penalty_from_context(case_context: str, *, payment_allocation: str = "principal") -> TemporalPenaltyResult | None:
    text = str(case_context or "")
    if not _PENALTY_DEMAND_RE.search(text):
        return None
    terms = parse_contractual_penalty_terms(text)
    base = base_amount_from_context(text)
    due = due_date_from_context(text)
    if terms is None or base is None or due is None:
        return None
    as_of = as_of_date_from_context(text)
    result = calc_temporal_contractual_penalty(
        base_amount=base,
        due_date=due,
        rate_percent_per_day=terms.rate_percent_per_day,
        cap_percent=terms.cap_percent,
        payments=payments_from_context(text),
        as_of_date=as_of,
        payment_allocation=payment_allocation,
    )
    LOGGER.info(
        "TEMPORAL_PENALTY_CALC base=%s due_date=%s delay_start=%s as_of=%s segments=%s total_before_cap=%s cap_amount=%s cap_reached_date=%s total=%s daily_after=%s outstanding_principal=%s convention=%s",
        base, due.isoformat(), (due + timedelta(days=1)).isoformat(), as_of.isoformat(), result.segments,
        result.total_before_cap, result.cap_amount,
        result.cap_reached_date.isoformat() if result.cap_reached_date else None,
        result.total, result.daily_after, result.outstanding_principal, result.convention,
    )
    return result


def _fmt_date(value: date) -> str:
    return value.strftime("%d.%m.%Y")


def _rate_percent(segment: dict[str, object]) -> str:
    base = int(segment["base"])
    daily = int(segment["rate_per_day"])
    return f"{(daily * 100 / base if base else 0):g}".replace(".", ",")


def render_penalty_calculation(result: TemporalPenaltyResult, *, language: str = "ru") -> list[str]:
    if result.total is None:
        return []
    lines = ["Детерминированный расчёт договорной неустойки:"]
    for index, segment in enumerate(result.segments, start=1):
        start, end = segment["from"], segment["to"]
        assert isinstance(start, date) and isinstance(end, date)
        lines.append(
            f"{index}) {_fmt_date(start)}–{_fmt_date(end)}: база {format_kzt(int(segment['base']))}; "
            f"ставка {_rate_percent(segment)}% в день; {format_kzt(int(segment['rate_per_day']))}/день × "
            f"{segment['days']} календарных дней = {format_kzt(int(segment['amount']))}."
        )
    if result.cap_amount is not None:
        reached = _fmt_date(result.cap_reached_date) if result.cap_reached_date else "не достигнут"
        lines.append(
            f"Сумма до ограничителя: {format_kzt(result.total_before_cap or 0)}. Договорный ограничитель: "
            f"{format_kzt(result.cap_amount)}; дата достижения ограничителя: {reached}. Итог на дату расчёта: {format_kzt(result.total)}."
        )
    else:
        lines.append(f"Итого договорная неустойка на дату расчёта: {format_kzt(result.total)}.")
    lines.append(
        f"Текущее ежедневное начисление после даты расчёта: {format_kzt(result.daily_after)} в день."
        if result.daily_after
        else "Текущее ежедневное начисление после даты расчёта: 0 тенге; договорный ограничитель достигнут."
    )
    lines.append(
        "Соглашения расчёта: просрочка начинается со дня, следующего за последним днём срока исполнения; "
        "календарные дни в каждом сегменте считаются включительно; в день частичной оплаты неустойка начисляется "
        "на прежнюю базу, платёж уменьшает основной долг со следующего календарного дня; платежи отнесены на основной долг."
    )
    return lines


def augment_case_context(case_context: str, result: TemporalPenaltyResult | None) -> str:
    if result is None or result.total is None:
        return case_context
    block = [
        "ДЕТЕРМИНИРОВАННЫЕ ДАННЫЕ KORGAN — модель не пересчитывает суммы и даты:",
        f"ТРЕБОВАНИЕ ИЗ ДОКУМЕНТА: уплатить договорную неустойку в размере {format_kzt(result.total)}.",
        *render_penalty_calculation(result),
    ]
    return f"{case_context.rstrip()}\n\n" + "\n".join(block)


def _canonical_penalty_demand(result: TemporalPenaltyResult, language: str) -> str:
    amount = format_kzt(result.total or 0)
    end = result.segments[-1]["to"] if result.segments else None
    as_of = _fmt_date(end) if isinstance(end, date) else "дату документа"
    if language == "kk":
        return f"Шарттық тұрақсыздық айыбын {as_of} жағдай бойынша {amount.replace(' тенге', ' теңге')} мөлшерінде төлеу."
    return f"Уплатить договорную неустойку по состоянию на {as_of} в размере {amount}."


def _preserved_transfer_tail(text: str) -> str:
    match = _TRANSFER_TAIL_RE.search(str(text or ""))
    return match.group(1).strip() if match else ""


def apply_penalty_result_to_draft(draft: Any, result: TemporalPenaltyResult | None, *, language: str = "ru") -> bool:
    if result is None or result.total is None:
        return False
    attr = "requests" if hasattr(draft, "requests") else "demands" if hasattr(draft, "demands") else ""
    if not attr:
        return False
    demands = list(getattr(draft, attr) or [])
    canonical = _canonical_penalty_demand(result, language)
    indices = [index for index, value in enumerate(demands) if _PENALTY_RE.search(str(value))]
    changed = False
    if indices:
        index = indices[0]
        tail = _preserved_transfer_tail(str(demands[index]))
        rewritten = canonical if not tail else f"{canonical.rstrip('.')} — {tail}"
        if demands[index] != rewritten:
            demands[index] = rewritten
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
    lines: list[str] = []
    for attr in ("title", "sender", "recipient", "claimant", "defendant", "facts", "legal_basis", "demands", "requests", "deadline", "consequences", "attachments"):
        value = getattr(draft, attr, None)
        if isinstance(value, list):
            lines.extend(str(item) for item in value if str(item).strip())
        elif value:
            lines.append(str(value))
    return lines


def _bank_complete(text: str) -> bool:
    upper = text.upper()
    return bool(_IBAN_RE.search(text) and _BIC_RE.search(text) and _KBE_RE.search(text) and "БАНК" in upper and _BIN_RE.search(text) and ("НАЗНАЧЕНИЕ ПЛАТЕЖА" in upper or "ТӨЛЕМ МАҚСАТЫ" in upper))


def _bank_requisites_from_source(case_context: str) -> str:
    text = str(case_context or "")
    iban, bic, kbe, bank = _IBAN_RE.search(text), _BIC_RE.search(text), _KBE_RE.search(text), _BANK_LINE_RE.search(text)
    if not (iban and bic and kbe and bank):
        return _BANK_MARKER
    name, bin_match, purpose = _NAME_RE.search(text), _BIN_RE.search(text), _PURPOSE_RE.search(text)
    recipient = name.group(1) if name else "[ДАННЫЕ: наименование получателя]"
    bin_text = bin_match.group(1) if bin_match else "[ДАННЫЕ: БИН получателя]"
    purpose_text = purpose.group(1).strip() if purpose else "[ДАННЫЕ: назначение платежа]"
    return (
        f"Банковские реквизиты получателя: {recipient}; БИН: {bin_text}; ИИК: {iban.group(1)}; "
        f"Банк: {' '.join(bank.group(1).split())}; БИК: {bic.group(1)}; КБе: {kbe.group(1)}; "
        f"Назначение платежа: {purpose_text}."
    )


def ensure_payment_requisites(draft: Any, case_context: str) -> bool:
    text = "\n".join(_document_lines(draft))
    if not _TRANSFER_RE.search(text) or _BANK_MARKER in text or _bank_complete(text):
        return False
    line = _bank_requisites_from_source(case_context)
    attr = "demands" if hasattr(draft, "demands") else "facts" if hasattr(draft, "facts") else ""
    if not attr:
        return False
    values = list(getattr(draft, attr) or [])
    if line in values:
        return False
    values.append(line)
    setattr(draft, attr, values)
    LOGGER.info("PAYMENT_REQUISITES_ENFORCED marker=%s", line == _BANK_MARKER)
    return True


def penalty_demand_issues(draft: Any) -> list[str]:
    demands = list(getattr(draft, "requests", []) or getattr(draft, "demands", []) or [])
    issues: list[str] = []
    for raw in demands:
        text = str(raw)
        if not (_PENALTY_RE.search(text) and _MONEY_DEMAND_RE.search(text)):
            continue
        if any(pattern.search(text) for pattern in _FORBIDDEN):
            issues.append("денежное требование о неустойке оставлено без числового расчёта")
        if not _MONEY_RE.search(text):
            issues.append("денежное требование о неустойке не содержит конкретной суммы")
    return list(dict.fromkeys(issues))


def payment_requisites_issues(draft: Any) -> list[str]:
    text = "\n".join(_document_lines(draft))
    if not _TRANSFER_RE.search(text) or _BANK_MARKER in text or _bank_complete(text):
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
    """Wrap existing claim/pretrial stages exactly once; add no model call."""
    global _INSTALLED
    if _INSTALLED:
        return
    from korgan.claim_state_duty import apply_professional_state_duty
    from korgan.pretrial import PretrialProductionService
    from korgan.professional_claim_finalizer import _recalculate_price
    from korgan.stable_legal_release import StableLegalProductionService

    current_pretrial = PretrialProductionService.draft_pretrial

    async def pretrial_with_temporal_money(self: PretrialProductionService, case_context: str, research: LegalResearch, language: str = "ru"):
        result = calculate_temporal_penalty_from_context(case_context)
        draft = await current_pretrial(self, augment_case_context(case_context, result), research, language=language)
        _enforce_or_raise(draft, case_context, result, language)
        return draft

    PretrialProductionService.draft_pretrial = pretrial_with_temporal_money  # type: ignore[assignment]
    current_claim = StableLegalProductionService.draft_claim

    async def claim_with_temporal_money(self: StableLegalProductionService, case_context: str, research: LegalResearch, language: str = "ru") -> ClaimDraft:
        result = calculate_temporal_penalty_from_context(case_context)
        draft = await current_claim(self, augment_case_context(case_context, result), research, language=language)
        changed = _enforce_or_raise(draft, case_context, result, language)
        if changed and result is not None and result.total is not None:
            _recalculate_price(draft)
            apply_professional_state_duty(case_context, research, draft)
        return draft

    StableLegalProductionService.draft_claim = claim_with_temporal_money  # type: ignore[assignment]
    _INSTALLED = True
    LOGGER.info("Installed temporal penalty + payment requisites hardening; no extra model round")
