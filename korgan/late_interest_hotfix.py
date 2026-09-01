from __future__ import annotations

from datetime import date, datetime, timedelta
import re
from zoneinfo import ZoneInfo

from korgan.contractual_penalty import (
    ContractualPenalty,
    ContractualPenaltyTerms,
    calc_contractual_penalty,
    parse_contractual_penalty_terms,
)
from korgan.partial_payments import find_partial_payments
from korgan.legal_calc import (
    ARTICLE_353_LABEL,
    ARTICLE_353_SOURCE_URL,
    DAYS_IN_YEAR,
    NEEDS_RATE_MARKER,
    base_rate_on,
    calc_late_payment_penalty,
    format_kzt,
    gosposhlina_line,
    late_penalty_line,
    needs_rate_marker,
    next_rate_decision_on,
    parse_all_amounts_kzt,
    parse_amount_kzt,
)
from korgan.calculation_document_gate import (
    DocumentAmounts,
    check_calculation_against_document,
)
from korgan.legal_calculation import (
    MoneyComponent,
    contractual_penalty_component,
    interval_penalty_component,
    late_interest_component,
    principal_component,
    render_calculation,
)
from korgan.penalty_engine import (
    PenaltyCalculation,
    PenaltyTerms,
    PrincipalEvent,
    RateType,
    calculate_penalty,
)
from korgan.legal_types import ClaimDraft, LegalResearch, VerificationStatus
from korgan.state_duty_final_hotfix import (
    ProductionOpenAILegalService as _BaseProductionOpenAILegalService,
    _enforce_single_state_duty_request,
)
from korgan.verified_openai import (
    _VERIFIED_RESEARCH_SCHEMA,
    _actual_response_urls,
    _canonical_url,
)


_ARTICLE_353_RE = re.compile(r"(?<!\d)353(?!\d)")
_GK_GENERAL_MARKER = "K940001000_"
_PENALTY_TERM = (
    r"(?:неустойк\w*|пен[яию]\b|штраф\w*|өсімпұл\w*|тұрақсыздық\s+айыб\w*|"
    r"ст\.?\s*353|стать\w*\s*353|пользован\w*\s+чужими\s+деньг\w*|"
    r"процент\w*\s+за\s+просроч\w*)"
)
_REQUEST_VERB = r"(?:прошу|требую|взыскать|взыщите|начислить|заявляю|добавьте|добавь|сұраймын|өндір\w*|талап\s+ет\w*)"

_EXPLICIT_PENALTY_PATTERNS = (
    re.compile(rf"{_REQUEST_VERB}[^.\n]{{0,180}}{_PENALTY_TERM}", re.IGNORECASE),
    re.compile(rf"{_PENALTY_TERM}[^.\n]{{0,180}}{_REQUEST_VERB}", re.IGNORECASE),
)

_PENALTY_LINE_RE = re.compile(
    r"(?:ст\.?\s*353|стать\w*\s*353|неустойк\w*|пен[яию]\b|штраф\w*|өсімпұл\w*|"
    r"тұрақсыздық\s+айыб\w*|пользован\w*\s+чужими\s+деньг\w*|"
    r"процент\w*\s+(?:по\s+денежн\w*|за\s+просроч\w*))",
    re.IGNORECASE,
)
_ARTICLE_353_LINE_RE = re.compile(
    r"(?:ст\.?\s*353|стать\w*\s*353|базов\w*\s+ставк\w*\s+(?:НБ|Национальн\w*\s+Банк))",
    re.IGNORECASE,
)
_TITLE_PENALTY_RE = re.compile(
    r"\s+(?:и|және)\s+(?:[а-яёәіңғүұқөһ]+\s+){0,3}(?:процент\w*|неустойк\w*|пен[иь]\w*|өсімпұл\w*|тұрақсыздық\s+айыб\w*)[^\n]*$",
    re.IGNORECASE,
)
_STATE_DUTY_OR_COST_RE = re.compile(
    r"(?:государственн\w*\s+пошлин\w*|госпошлин\w*|судебн\w*\s+(?:расход\w*|издерж\w*)|"
    r"расход\w*\s+на\s+(?:оплат\w*\s+)?представител\w*)",
    re.IGNORECASE,
)
_PROPERTY_REQUEST_RE = re.compile(
    r"(?:взыск\w*|вернут\w*|возврат\w*|долг\w*|задолженн\w*|неустойк\w*|пен[яию]\b|штраф\w*|"
    r"убыт\w*|ущерб\w*|компенсац\w*|өндір\w*|берешек\w*|қарыз\w*|өсімпұл\w*|тұрақсыздық\s+айыб\w*)",
    re.IGNORECASE,
)
_AWARDED_AMOUNT_RE = re.compile(
    r"(?:в\s+размере|в\s+сумме|сумм\w*|мөлшерінде|сомасында)\s*"
    r"(?P<amount>\d[\d\s\u00a0]*(?:[.,]\d{1,2})?\s*(?:тенге|теңге|тг\b|₸|kzt))",
    re.IGNORECASE,
)
_MONEY_TOKEN_RE = re.compile(
    r"(?<!\d)\d[\d\s\u00a0]*(?:[.,]\d{1,2})?\s*(?:тенге|теңге|тг\b|₸|kzt)",
    re.IGNORECASE,
)
_PENALTY_AMOUNT_NEAR_RE = re.compile(
    r"(?:неустойк\w*|пен[яию]\b|штраф\w*|өсімпұл\w*|тұрақсыздық\s+айыб\w*)"
    r"(?:\s+(?:в\s+размере|в\s+сумме|составля\w*|мөлшерінде|сомасында)\s+|[\s:—-]{1,12})"
    r"(?P<amount>\d[\d\s\u00a0]*(?:[.,]\d{1,2})?\s*(?:тенге|теңге|тг\b|₸|kzt))",
    re.IGNORECASE,
)

_MONTHS = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}
_DATE_TOKEN = (
    r"(?:\d{1,2}[./-]\d{1,2}[./-]\d{4}|"
    r"\d{1,2}\s+(?:января|февраля|марта|апреля|мая|июня|июля|августа|"
    r"сентября|октября|ноября|декабря)\s+\d{4}(?:\s+года)?)"
)
_DUE_RE = re.compile(
    rf"(?:вернут\w*|возврат\w*|погас\w*|обязал\w*\s+вернут\w*)"
    rf"[^.\n]{{0,160}}?(?:не\s+позднее|до)\s+(?P<date>{_DATE_TOKEN})",
    re.IGNORECASE,
)
_PAYMENT_DUE_EXPIRED_RE = re.compile(
    rf"(?:срок\s+оплат\w*|срок\s+платеж\w*)\s+(?:ист[её]к|наступил|был)[^\d]{{0,40}}(?P<date>{_DATE_TOKEN})",
    re.IGNORECASE,
)
_PAYMENT_WITHIN_FROM_RE = re.compile(
    rf"оплат\w*\s+в\s+течени[еи]\s+(?P<days>\d{{1,4}})\s+(?:календарн\w*\s+)?дн\w*"
    rf"[^.\n]{{0,80}}?(?:с|от)\s+(?P<date>{_DATE_TOKEN})",
    re.IGNORECASE,
)

ARTICLE_353_MISSING_NOTE = (
    "Клиент заявил требование о неустойке за просрочку, но статья 353 ГК РК "
    "не прошла source-bound проверку в текущем legal research; требование сохранено как требующее проверки."
)
DUE_DATE_MISSING_NOTE = (
    "Для расчёта неустойки по статье 353 не удалось однозначно установить срок исполнения; "
    "требуется проверить дату начала просрочки."
)
PARTIAL_PAYMENT_NOTE = (
    "В материалах дела указана частичная оплата долга. Неустойка начисляется на остаток "
    "задолженности за каждый отрезок периода отдельно, поэтому расчёт одной суммой за весь "
    "период дал бы завышенное требование; расчёт по интервалам требует проверки дат и сумм "
    "платежей юристом."
)
PARTIAL_PAYMENT_UNCLEAR_NOTE = (
    "В материалах дела упоминается частичная оплата, но её дату и сумму нельзя однозначно "
    "установить. Пока платежи не подтверждены, размер неустойки не рассчитывается: "
    "начисление на первоначальный долг завысило бы требование."
)
CONTRACT_DUE_DATE_MISSING_NOTE = (
    "Договорная неустойка заявлена и её ставка распознана, но дату начала просрочки нельзя "
    "однозначно установить из материалов дела."
)
CONTRACT_TERMS_MISSING_NOTE = (
    "Клиент заявил неустойку, но договорную ставку нельзя однозначно извлечь из материалов, "
    "а статья 353 ГК РК не подтверждена source-bound исследованием."
)
RATE_MISSING_NOTE = (
    "Базовая ставка НБ РК для даты предъявления иска не подтверждена актуальным внутренним справочником; "
    "расчёт неустойки по статье 353 не выполнен."
)


def rate_missing_note(day: date) -> str:
    """То же замечание юристу, но с датой ближайшего заседания Нацбанка.

    Замечание «ставка не подтверждена справочником» звучит как неисправность и
    подталкивает искать её в справочнике. Если же заседание ещё не состоялось,
    искать нечего ни в справочнике, ни где-либо ещё, и единственное осмысленное
    действие — дождаться объявления. Дата заседания опубликована заранее,
    поэтому здесь она и называется: замечание превращается из жалобы в срок.
    """
    announcement = next_rate_decision_on(day)
    if announcement is None:
        return RATE_MISSING_NOTE
    return (
        f"{RATE_MISSING_NOTE} Решение Нацбанка по базовой ставке на "
        f"{day.strftime('%d.%m.%Y')} объявляется {announcement.strftime('%d.%m.%Y')} — "
        "до этой даты ставку не подтвердит ни один источник."
    )


def _today_kz() -> date:
    return datetime.now(ZoneInfo("Asia/Almaty")).date()


def _explicit_penalty_requested(case_context: str) -> bool:
    return any(pattern.search(case_context or "") for pattern in _EXPLICIT_PENALTY_PATTERNS)


def _research_has_article_353(research: LegalResearch) -> bool:
    for claim in research.verified_claims:
        if _ARTICLE_353_RE.search(claim) and _GK_GENERAL_MARKER.lower() in claim.lower():
            return True
    has_article = any(_ARTICLE_353_RE.search(claim) for claim in research.verified_claims)
    has_source = any(_GK_GENERAL_MARKER.lower() in url.lower() for url in research.source_urls)
    return has_article and has_source


def _parse_date_token(raw: str) -> date | None:
    text = (raw or "").strip().lower().replace(" года", "")
    for fmt in ("%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    match = re.fullmatch(r"(\d{1,2})\s+([а-яё]+)\s+(\d{4})", text)
    if not match:
        return None
    month = _MONTHS.get(match.group(2))
    if not month:
        return None
    try:
        return date(int(match.group(3)), month, int(match.group(1)))
    except ValueError:
        return None


def _extract_due_date(case_context: str) -> date | None:
    candidates: list[date] = []

    def add(raw: str) -> None:
        parsed = _parse_date_token(raw)
        if parsed and parsed not in candidates:
            candidates.append(parsed)

    for match in _DUE_RE.finditer(case_context or ""):
        add(match.group("date"))
    for match in _PAYMENT_DUE_EXPIRED_RE.finditer(case_context or ""):
        add(match.group("date"))
    for match in _PAYMENT_WITHIN_FROM_RE.finditer(case_context or ""):
        base = _parse_date_token(match.group("date"))
        if base:
            calculated = base + timedelta(days=int(match.group("days")))
            if calculated not in candidates:
                candidates.append(calculated)

    return candidates[0] if len(candidates) == 1 else None


def _principal_amount(draft: ClaimDraft) -> int | None:
    """Prefer the standalone principal request over a model-written total claim price."""
    for request in draft.requests:
        if _PENALTY_LINE_RE.search(request) or _STATE_DUTY_OR_COST_RE.search(request):
            continue
        lowered = request.lower()
        if any(marker in lowered for marker in ("основн", "долг", "задолж", "негізгі", "берешек", "қарыз")):
            amount = parse_amount_kzt(request)
            if amount:
                return amount
    return parse_amount_kzt(draft.price_of_claim)


def _strip_penalty_everywhere(draft: ClaimDraft) -> None:
    """Remove a model-invented penalty coherently from every claim field."""
    draft.requests = [item for item in draft.requests if not _PENALTY_LINE_RE.search(item)]
    draft.legal_basis = [item for item in draft.legal_basis if not _PENALTY_LINE_RE.search(item)]
    draft.facts = [item for item in draft.facts if not _PENALTY_LINE_RE.search(item)]
    draft.attachments = [item for item in draft.attachments if not _PENALTY_LINE_RE.search(item)]
    draft.late_interest = ""
    draft.title = _TITLE_PENALTY_RE.sub("", draft.title or "").strip()
    _drop_penalty_calculation(draft)


def _drop_article_353_lines(draft: ClaimDraft) -> None:
    draft.legal_basis = [item for item in draft.legal_basis if not _ARTICLE_353_LINE_RE.search(item)]


def _request_awarded_amount(request: str) -> int | None:
    match = _AWARDED_AMOUNT_RE.search(request or "")
    if match:
        return parse_amount_kzt(match.group("amount"))
    amounts = parse_all_amounts_kzt(request or "")
    if not amounts:
        return None
    if _PENALTY_LINE_RE.search(request or "") and len(amounts) > 1:
        return amounts[-1]
    return amounts[0]


def _existing_penalty_amount(draft: ClaimDraft) -> int | None:
    for request in draft.requests or []:
        if _PENALTY_LINE_RE.search(str(request)):
            amount = _request_awarded_amount(str(request))
            if amount is not None:
                return amount
    return None


def _replace_exact_amounts(text: str, replacements: dict[int, int]) -> str:
    if not replacements:
        return text

    def replace(match: re.Match[str]) -> str:
        current = parse_amount_kzt(match.group(0))
        target = replacements.get(current) if current is not None else None
        return format_kzt(target) if target is not None else match.group(0)

    return _MONEY_TOKEN_RE.sub(replace, text or "")


def _sync_calculated_penalty_narrative(
    draft: ClaimDraft,
    *,
    principal: int,
    new_penalty: int,
    old_penalty: int | None,
    old_price: int | None,
) -> None:
    """Keep penalty-bearing facts/attachments aligned with deterministic arithmetic."""
    replacements: dict[int, int] = {}
    if old_penalty is not None and old_penalty not in {principal, new_penalty}:
        replacements[old_penalty] = new_penalty
    new_price = principal + new_penalty
    if old_price is not None and old_price not in {principal, new_price}:
        replacements[old_price] = new_price
    if not replacements:
        return

    draft.facts = [
        _replace_exact_amounts(str(item), replacements) if _PENALTY_LINE_RE.search(str(item)) else str(item)
        for item in draft.facts
    ]
    draft.attachments = [
        _replace_exact_amounts(str(item), replacements) if _PENALTY_LINE_RE.search(str(item)) else str(item)
        for item in draft.attachments
    ]


def _explicit_penalty_amount_from_context(case_context: str) -> int | None:
    """Return one source-bound penalty amount only when directly tied to the penalty label."""
    values: list[int] = []
    for match in _PENALTY_AMOUNT_NEAR_RE.finditer(case_context or ""):
        amount = parse_amount_kzt(match.group("amount") or "")
        if amount is not None and amount not in values:
            values.append(amount)
    return values[0] if len(values) == 1 else None


def _mark_penalty_for_verification(
    draft: ClaimDraft, reason: str, *, case_context: str, detail: str = ""
) -> None:
    """Keep the remedy while discarding any model-only monetary figure.

    ``reason`` попадает в саму просительную часть и потому должен читаться как
    пометка на полях иска. Разбор расхождения — какая сумма где стоит — идёт
    в ``detail`` и остаётся в замечаниях для юриста: в «ПРОШУ СУД» ему не
    место, там перечисление чужих сумм читается как заявленное требование.
    """
    suffix = f"[ТРЕБУЕТ ПРОВЕРКИ: {reason}]"
    source_amount = _explicit_penalty_amount_from_context(case_context)
    updated = [str(item) for item in draft.requests if not _PENALTY_LINE_RE.search(str(item))]
    if source_amount is not None:
        updated.append(
            f"Взыскать заявленную клиентом неустойку в размере {format_kzt(source_amount)}. {suffix}"
        )
    else:
        updated.append(f"Взыскать заявленную клиентом неустойку. {suffix}")
    draft.requests = updated
    _drop_penalty_calculation(draft)
    note = f"{reason} {detail}".strip() if detail else reason
    if note not in draft.verification_notes:
        draft.verification_notes.append(note)
    draft.status = VerificationStatus.NEEDS_VERIFICATION


def _component_label(request: str) -> str:
    lowered = (request or "").lower()
    if "договорн" in lowered and _PENALTY_LINE_RE.search(lowered):
        return "договорная неустойка"
    if _ARTICLE_353_RE.search(lowered):
        return "неустойка по статье 353 ГК РК"
    if _PENALTY_LINE_RE.search(lowered):
        return "неустойка"
    if any(marker in lowered for marker in ("основн", "долг", "задолж", "негізгі", "берешек", "қарыз")):
        return "основной долг"
    return "имущественное требование"


def _property_components(draft: ClaimDraft) -> tuple[list[tuple[str, int, str]], bool]:
    """Имущественные требования просительной части: ярлык, сумма и сама строка.

    Один разбор обслуживает и цену иска, и раздел «Расчёт взыскиваемых сумм»:
    иначе итог расчёта и цена иска считались бы разными обходами одного текста и
    со временем разошлись бы. Второй элемент результата — признак того, что хотя
    бы одно требование не разрешилось в число; тогда обе величины обязаны
    остановиться, а не публиковать половину.
    """
    components: list[tuple[str, int, str]] = []
    unresolved = False

    for request in list(draft.requests or []):
        text = str(request)
        if _STATE_DUTY_OR_COST_RE.search(text):
            continue
        if not _PROPERTY_REQUEST_RE.search(text):
            continue
        upper = text.upper()
        if "[ТРЕБУЕТ РАСЧ" in upper or "[ТРЕБУЕТ ПРОВЕРКИ" in upper:
            unresolved = True
            continue
        amount = _request_awarded_amount(text)
        if amount is None:
            unresolved = True
            continue
        components.append((_component_label(text), amount, text))

    return components, unresolved


def _upper_first(text: str) -> str:
    return text[:1].upper() + text[1:]


def _write_deterministic_calculation(draft: ClaimDraft, detail: MoneyComponent) -> None:
    """Сделать детерминированную арифметику содержанием раздела расчёта.

    Раздел расчёта — это арифметика, а арифметику в KORGAN пишет не модель.
    После пересчёта неустойки прежний расчёт модели остаётся с прежней суммой,
    прежней ставкой и прежним итогом: документ начинает утверждать два разных
    числа. Поэтому раздел собирается заново из тех же требований, из которых
    считается цена иска, а посчитанная позиция раскрывается целиком — база,
    ставка, период, дни, формула и договорный предел.

    Если хотя бы одно имущественное требование не разрешилось в число, раздел
    очищается: неполный расчёт с итогом хуже, чем честно отсутствующий раздел,
    и document_quality отметит его отсутствие.
    """
    components, unresolved = _property_components(draft)
    if unresolved or not components:
        draft.calculation = []
        return

    rendered: list[MoneyComponent] = []
    used_detail = False
    for label, amount, text in components:
        if not used_detail and amount == detail.amount and _PENALTY_LINE_RE.search(text):
            rendered.append(detail)
            used_detail = True
        elif label == "основной долг":
            rendered.append(principal_component(amount, basis=""))
        else:
            rendered.append(MoneyComponent(title=_upper_first(label), basis="", amount=amount))

    draft.calculation = render_calculation(rendered)


def _drop_penalty_calculation(draft: ClaimDraft) -> None:
    """Убрать расчёт, построенный вокруг неустойки, которой больше нет.

    Неустойка либо снята как выдуманная моделью, либо переведена в статус
    требующей проверки. Оставшийся расчёт продолжал бы называть её размер и
    включать его в итог — то есть утверждать сумму, которую документ уже не
    заявляет.
    """
    if any(_PENALTY_LINE_RE.search(str(line)) for line in draft.calculation or []):
        draft.calculation = []


def _recompute_claim_price_and_duty(draft: ClaimDraft, case_context: str) -> None:
    """Цена иска = сумма всех определённых имущественных требований, без судебных расходов."""
    scanned, unresolved = _property_components(draft)
    components: list[tuple[str, int]] = [(label, amount) for label, amount, _ in scanned]

    if unresolved:
        draft.price_of_claim = "[ТРЕБУЕТ РАСЧЁТА]"
        draft.state_duty = gosposhlina_line(case_context, draft.price_of_claim)
        _enforce_single_state_duty_request(draft)
        draft.status = VerificationStatus.NEEDS_VERIFICATION
        return

    if not components:
        principal = _principal_amount(draft)
        if principal is None:
            draft.price_of_claim = "[ТРЕБУЕТ РАСЧЁТА]"
            draft.state_duty = gosposhlina_line(case_context, draft.price_of_claim)
            _enforce_single_state_duty_request(draft)
            draft.status = VerificationStatus.NEEDS_VERIFICATION
            return
        components = [("основной долг", principal)]

    total = sum(amount for _, amount in components)
    if len(components) == 1:
        draft.price_of_claim = format_kzt(total)
    else:
        detail = " + ".join(f"{label} {format_kzt(amount)}" for label, amount in components)
        draft.price_of_claim = f"{format_kzt(total)} ({detail})"
    draft.state_duty = gosposhlina_line(case_context, draft.price_of_claim)
    _enforce_single_state_duty_request(draft)


def _interval_penalty_line(calculation: PenaltyCalculation, *, rate_label: str, basis: str) -> str:
    """Строка «неустойка» для дела, где долг гасили частями.

    Таблица разворачивается прямо в строке: без неё сумма выглядит взятой
    ниоткуда, потому что ни на один остаток долга целиком она не делится.
    """
    first = calculation.intervals[0]
    last = calculation.intervals[-1]
    rows = "; ".join(
        f"{i.period_from.strftime('%d.%m.%Y')}—{i.period_to.strftime('%d.%m.%Y')}: "
        f"{format_kzt(i.principal)} × {i.rate:g}% × {i.days} дн. = {format_kzt(i.subtotal)}"
        for i in calculation.intervals
    )
    cap = ""
    if calculation.capped and calculation.cap_amount is not None:
        cap = (
            f"; начислено {format_kzt(calculation.raw_total)}, "
            f"предъявлено в пределах ограничения {format_kzt(calculation.cap_amount)}"
        )
    return (
        f"{format_kzt(calculation.total)} за период с {first.period_from.strftime('%d.%m.%Y')} "
        f"по {last.period_to.strftime('%d.%m.%Y')} (ставка {rate_label}; {basis}; "
        f"расчёт по остатку задолженности: {rows}){cap}"
    )


def _interval_penalty_request(
    calculation: PenaltyCalculation, *, title: str, rate_label: str, basis: str
) -> str:
    first = calculation.intervals[0]
    last = calculation.intervals[-1]
    return (
        f"Взыскать с ответчика в пользу истца {title} {basis} в размере "
        f"{format_kzt(calculation.total)} за период с {first.period_from.strftime('%d.%m.%Y')} "
        f"по {last.period_to.strftime('%d.%m.%Y')} исходя из ставки {rate_label}, "
        f"с начислением на остаток задолженности после каждой частичной оплаты."
    )


def _contractual_penalty_line(penalty: ContractualPenalty) -> str:
    terms = penalty.terms
    clause = f"; пункт {terms.clause} договора" if terms.clause else "; условие договора о неустойке"
    cap = ""
    if terms.cap_percent is not None and penalty.cap_reached_on is not None:
        cap = (
            f"; лимит {terms.cap_percent:g}% = {format_kzt(penalty.cap_amount or 0)}, "
            f"достигается {penalty.cap_reached_on.strftime('%d.%m.%Y')}"
        )
    return (
        f"{format_kzt(penalty.amount)} за период с {penalty.start.strftime('%d.%m.%Y')} "
        f"по {penalty.end.strftime('%d.%m.%Y')} ({penalty.days} дн.; договорная ставка "
        f"{terms.rate_percent_per_day:g}% от суммы задолженности за каждый день просрочки{clause}{cap}): "
        f"{format_kzt(penalty.principal)} × {terms.rate_percent_per_day:g}% × {penalty.days} дн."
    )


def _contractual_penalty_request(penalty: ContractualPenalty) -> str:
    terms = penalty.terms
    clause = f"по пункту {terms.clause} договора" if terms.clause else "по условию договора о неустойке"
    text = (
        f"Взыскать с ответчика в пользу истца договорную неустойку {clause} "
        f"в размере {format_kzt(penalty.amount)} за период с {penalty.start.strftime('%d.%m.%Y')} "
        f"по {penalty.end.strftime('%d.%m.%Y')} ({penalty.days} дн.) исходя из ставки "
        f"{terms.rate_percent_per_day:g}% от суммы задолженности за каждый день просрочки"
    )
    if terms.cap_percent is None:
        return text + "; за последующий период — по день фактической уплаты суммы долга."
    if penalty.capped:
        reached = penalty.cap_reached_on.strftime("%d.%m.%Y") if penalty.cap_reached_on else "установленную дату"
        return (
            text
            + f"; предельный размер {terms.cap_percent:g}% от суммы задолженности достигнут {reached}, "
            "дальнейшее начисление сверх договорного лимита не заявляется."
        )
    return (
        text
        + "; за последующий период — по день фактической уплаты суммы долга, "
        f"но не более {terms.cap_percent:g}% от суммы задолженности."
    )


def _calculation_line_amount(draft: ClaimDraft, marker: str) -> int | None:
    """Сумма из позиции раздела расчёта, название которой содержит слово.

    Слово ищется только в названии позиции — до первого двоеточия. Дальше идут
    база, ставка и формула, где те же слова встречаются в другом значении.
    """
    for line in draft.calculation or []:
        title = str(line).split(":", 1)[0].lower()
        if marker in title:
            return parse_amount_kzt(str(line))
    return None


def _engine_reference(
    principal: int, start: date, end: date, terms: PenaltyTerms
) -> PenaltyCalculation:
    """Тот же период, посчитанный движком, — эталон для сверки с документом.

    Однопериодные дела считают исторические калькуляторы, и переписывать их
    ради гейта незачем: на 120 сочетаниях суммы, ставки и длины периода они
    сходятся с движком до тенге. Но гейту нужен ``PenaltyCalculation``, а
    собрать его вручную из готового числа значило бы сверять документ с тем
    же самым числом. Здесь период считается вторым, независимым путём: если
    два калькулятора разойдутся, требование уйдёт юристу, а не в суд.
    """
    return calculate_penalty(principal, start, end, terms)


def _enforce_calculation_gate(
    draft: ClaimDraft,
    calculation: PenaltyCalculation,
    *,
    principal: int,
    case_context: str,
) -> None:
    """Сверить посчитанное с тем, что в итоге написано в документе.

    Расчёт может быть верным, а документ негодным: строка неустойки, таблица
    расчёта и просительная часть переписываются разными ветками кода, и
    достаточно одной, чтобы в иске оказались три разных числа. Сверка берёт
    суммы из готового текста, а не из расчёта, — иначе она сравнивала бы расчёт
    сам с собой и пропускала ровно ту ошибку, ради которой существует.

    Расхождение не исправляется подстановкой «правильного» числа: неизвестно,
    какая часть документа устарела. Требование снимается целиком и уходит юристу.
    """
    components, unresolved = _property_components(draft)
    penalties = [amount for label, amount, _ in components if "неустойк" in label]
    principals = [amount for label, amount, _ in components if label == "основной долг"]
    others = sum(
        amount
        for label, amount, _ in components
        if "неустойк" not in label and label != "основной долг"
    )
    reasoning = parse_amount_kzt(draft.late_interest)
    in_calculation = _calculation_line_amount(draft, "неустойк")
    total = parse_amount_kzt(draft.price_of_claim)
    principal_in_document = _calculation_line_amount(draft, "основной долг")

    missing = (
        unresolved
        or len(penalties) != 1
        or len(principals) != 1
        or reasoning is None
        or in_calculation is None
        or total is None
        or principal_in_document is None
    )
    if missing:
        reasons = ("суммы документа не сверяются с расчётом: требование изложено неоднозначно",)
    else:
        reasons = check_calculation_against_document(
            calculation,
            DocumentAmounts(
                principal_in_document=principal_in_document,
                penalty_in_reasoning=reasoning,
                penalty_in_calculation=in_calculation,
                penalty_in_relief=penalties[0],
                principal_in_relief=principals[0],
                total_in_relief=total,
                other_verified_claims=others,
            ),
            principal=principal,
        ).reasons
    if not reasons:
        return

    _drop_article_353_lines(draft)
    _mark_penalty_for_verification(
        draft,
        "расчёт неустойки не сошёлся с текстом документа",
        case_context=case_context,
        detail="Расхождения: " + "; ".join(reasons) + ".",
    )
    _recompute_claim_price_and_duty(draft, case_context)


def _note_principal_needs_check(draft: ClaimDraft, events: tuple[PrincipalEvent, ...]) -> None:
    """Напомнить, что частичная оплата могла быть не учтена в основном долге.

    Неустойку код пересчитывает сам, а сумму основного долга — нет: платёж мог
    быть уже вычтен клиентом, а мог и не быть, и по тексту дела это неразличимо.
    Молча уменьшить требование значило бы отказаться от части долга за клиента,
    молча оставить — предъявить погашенное. Решение остаётся за юристом.
    """
    if not events:
        return
    paid = sum(-int(event.delta) for event in events if event.delta < 0)
    if paid <= 0:
        return
    note = (
        f"По материалам дела должник погасил {format_kzt(paid)}. Неустойка рассчитана на "
        "остаток задолженности по каждому отрезку периода; проверьте, уменьшена ли на эту "
        "сумму заявленная сумма основного долга."
    )
    if note not in draft.verification_notes:
        draft.verification_notes.append(note)


def _apply_article_353_by_intervals(
    case_context: str,
    draft: ClaimDraft,
    *,
    research: LegalResearch,
    start: date,
    end: date,
    principal: int,
    events: tuple[PrincipalEvent, ...],
) -> None:
    """Неустойка по статье 353 ГК РК при частичном погашении долга."""
    rate = base_rate_on(end)
    if rate is None:
        draft.late_interest = needs_rate_marker(end)
        _mark_penalty_for_verification(
            draft, rate_missing_note(end), case_context=case_context
        )
        _recompute_claim_price_and_duty(draft, case_context)
        return

    source = next(
        (url for url in research.source_urls if _GK_GENERAL_MARKER.lower() in url.lower()),
        "",
    )
    calculation = calculate_penalty(
        principal,
        start,
        end,
        PenaltyTerms(
            rate=rate,
            rate_type=RateType.PER_YEAR,
            days_in_year=DAYS_IN_YEAR,
            legal_basis=ARTICLE_353_LABEL,
            legal_basis_source=source,
            rate_source=f"базовая ставка Национального Банка РК на {end.strftime('%d.%m.%Y')}",
        ),
        events=events,
        breach="просрочка оплаты",
    )
    if not calculation.ready or not calculation.intervals:
        reason = "; ".join(calculation.reasons) or PARTIAL_PAYMENT_UNCLEAR_NOTE
        _drop_article_353_lines(draft)
        _mark_penalty_for_verification(draft, reason, case_context=case_context)
        _recompute_claim_price_and_duty(draft, case_context)
        return

    rate_label = f"{rate:g}% годовых (базовая ставка НБ РК на {end.strftime('%d.%m.%Y')})"
    _note_principal_needs_check(draft, events)
    old_penalty = _existing_penalty_amount(draft)
    old_price = parse_amount_kzt(draft.price_of_claim)
    _sync_calculated_penalty_narrative(
        draft,
        principal=principal,
        new_penalty=calculation.total,
        old_penalty=old_penalty,
        old_price=old_price,
    )
    draft.requests = [item for item in draft.requests if not _PENALTY_LINE_RE.search(item)]
    draft.legal_basis = [item for item in draft.legal_basis if not _PENALTY_LINE_RE.search(item)]
    draft.legal_basis.append(
        "В соответствии с пунктами 1 и 2 статьи 353 Гражданского кодекса Республики Казахстан "
        "за неправомерное пользование чужими деньгами вследствие просрочки денежного обязательства "
        "подлежит уплате неустойка; при частичном погашении долга неустойка за каждый отрезок "
        "периода начисляется на остаток задолженности, существовавший в этом отрезке."
    )
    draft.late_interest = _interval_penalty_line(
        calculation, rate_label=rate_label, basis=ARTICLE_353_LABEL
    )
    draft.requests.append(
        _interval_penalty_request(
            calculation,
            title="неустойку",
            rate_label=rate_label,
            basis="по статье 353 ГК РК",
        )
    )
    _recompute_claim_price_and_duty(draft, case_context)
    _write_deterministic_calculation(
        draft,
        interval_penalty_component(
            calculation,
            title="Неустойка за пользование чужими деньгами",
            basis=ARTICLE_353_LABEL,
            rate_label=rate_label,
        ),
    )
    _enforce_calculation_gate(
        draft, calculation, principal=principal, case_context=case_context
    )


def _apply_contractual_penalty_by_intervals(
    case_context: str,
    draft: ClaimDraft,
    *,
    terms: ContractualPenaltyTerms,
    start: date,
    end: date,
    principal: int,
    events: tuple[PrincipalEvent, ...],
) -> bool:
    """Договорная неустойка при частичном погашении долга — по интервалам."""
    clause = f"пункт {terms.clause} договора" if terms.clause else "условие договора о неустойке"
    calculation = calculate_penalty(
        principal,
        start,
        end,
        PenaltyTerms(
            rate=terms.rate_percent_per_day,
            rate_type=RateType.PER_DAY,
            contract_basis=clause,
            # Ставку и предел извлёк один и тот же fail-closed разбор из текста
            # договора: источник у них общий, поэтому предел подтверждён ровно
            # в той же мере, что и сама ставка.
            rate_source=clause,
            cap_percent=terms.cap_percent,
            cap_verified=terms.cap_percent is not None,
        ),
        events=events,
        breach="просрочка оплаты",
    )
    if not calculation.ready or not calculation.intervals:
        reason = "; ".join(calculation.reasons) or PARTIAL_PAYMENT_UNCLEAR_NOTE
        _drop_article_353_lines(draft)
        _mark_penalty_for_verification(draft, reason, case_context=case_context)
        _recompute_claim_price_and_duty(draft, case_context)
        return True

    rate_label = f"{terms.rate_percent_per_day:g}% за каждый день просрочки"
    _note_principal_needs_check(draft, events)
    old_penalty = _existing_penalty_amount(draft)
    old_price = parse_amount_kzt(draft.price_of_claim)
    _sync_calculated_penalty_narrative(
        draft,
        principal=principal,
        new_penalty=calculation.total,
        old_penalty=old_penalty,
        old_price=old_price,
    )
    draft.requests = [item for item in draft.requests if not _PENALTY_LINE_RE.search(item)]
    _drop_article_353_lines(draft)
    basis_line = (
        f"{clause[0].upper()}{clause[1:]} предусмотрена договорная неустойка в размере "
        f"{terms.rate_percent_per_day:g}% от суммы задолженности за каждый день просрочки; "
        "при частичном погашении долга неустойка начисляется на остаток задолженности."
    )
    if basis_line not in draft.legal_basis:
        draft.legal_basis.append(basis_line)
    draft.late_interest = _interval_penalty_line(
        calculation, rate_label=rate_label, basis=clause
    )
    draft.requests.append(
        _interval_penalty_request(
            calculation,
            title="договорную неустойку",
            rate_label=rate_label,
            basis=f"по {clause}",
        )
    )
    _recompute_claim_price_and_duty(draft, case_context)
    _write_deterministic_calculation(
        draft,
        interval_penalty_component(
            calculation,
            title="Договорная неустойка",
            basis=clause,
            rate_label=rate_label,
        ),
    )
    _enforce_calculation_gate(
        draft, calculation, principal=principal, case_context=case_context
    )
    return True


def _apply_contractual_penalty(
    case_context: str,
    draft: ClaimDraft,
    *,
    terms: ContractualPenaltyTerms,
    filing_date: date,
    events: tuple[PrincipalEvent, ...] = (),
) -> bool:
    principal = _principal_amount(draft)
    due_date = _extract_due_date(case_context)
    if principal is None or due_date is None:
        _drop_article_353_lines(draft)
        _mark_penalty_for_verification(draft, CONTRACT_DUE_DATE_MISSING_NOTE, case_context=case_context)
        _recompute_claim_price_and_duty(draft, case_context)
        return True

    start = due_date + timedelta(days=1)
    if filing_date < start:
        reason = "На дату подачи иска установленный срок оплаты ещё не истёк; период просрочки отсутствует."
        _drop_article_353_lines(draft)
        _mark_penalty_for_verification(draft, reason, case_context=case_context)
        _recompute_claim_price_and_duty(draft, case_context)
        return True

    if events:
        # Долг гасили частями: одна формула на весь период начислила бы
        # неустойку на первоначальный долг и после платежей.
        return _apply_contractual_penalty_by_intervals(
            case_context, draft, terms=terms, start=start, end=filing_date,
            principal=principal, events=events,
        )

    old_penalty = _existing_penalty_amount(draft)
    old_price = parse_amount_kzt(draft.price_of_claim)
    penalty = calc_contractual_penalty(principal, terms, start, filing_date)
    _sync_calculated_penalty_narrative(
        draft,
        principal=principal,
        new_penalty=penalty.amount,
        old_penalty=old_penalty,
        old_price=old_price,
    )
    draft.requests = [item for item in draft.requests if not _PENALTY_LINE_RE.search(item)]
    _drop_article_353_lines(draft)
    clause = f"Пунктом {terms.clause} договора" if terms.clause else "Условием договора о неустойке"
    basis = (
        f"{clause} предусмотрена договорная неустойка в размере {terms.rate_percent_per_day:g}% "
        "от суммы задолженности за каждый день просрочки"
        + (f", но не более {terms.cap_percent:g}% от суммы задолженности." if terms.cap_percent is not None else ".")
    )
    if basis not in draft.legal_basis:
        draft.legal_basis.append(basis)
    draft.late_interest = _contractual_penalty_line(penalty)
    draft.requests.append(_contractual_penalty_request(penalty))
    _recompute_claim_price_and_duty(draft, case_context)
    _write_deterministic_calculation(draft, contractual_penalty_component(penalty))
    _enforce_calculation_gate(
        draft,
        _engine_reference(
            principal,
            start,
            filing_date,
            PenaltyTerms(
                rate=terms.rate_percent_per_day,
                rate_type=RateType.PER_DAY,
                contract_basis=clause,
                rate_source=clause,
                cap_percent=terms.cap_percent,
                cap_verified=terms.cap_percent is not None,
            ),
        ),
        principal=principal,
        case_context=case_context,
    )
    return True


def _apply_verified_penalty(
    case_context: str,
    research: LegalResearch,
    draft: ClaimDraft,
    *,
    filing_date: date,
) -> None:
    requested = _explicit_penalty_requested(case_context)
    if not requested:
        _strip_penalty_everywhere(draft)
        _recompute_claim_price_and_duty(draft, case_context)
        return

    # Частичная оплата разрывает период просрочки: до неё неустойка идёт от
    # полного долга, после — от остатка. Обе имеющиеся формулы считают одну
    # сумму по одной ставке за один отрезок, поэтому платёж середины периода
    # в расчёт не попадает и требование выходит завышенным — молча, ровно то
    # число, которое первым пересчитает ответчик.
    payments = find_partial_payments(case_context)
    if payments.mentioned and (payments.unparsed or not payments.payments):
        # Оплата была, а её дату или размер установить не удалось. Считать
        # нечего: начисление на первоначальный долг завысило бы требование.
        _drop_article_353_lines(draft)
        _mark_penalty_for_verification(draft, PARTIAL_PAYMENT_UNCLEAR_NOTE, case_context=case_context)
        _recompute_claim_price_and_duty(draft, case_context)
        return

    contractual_terms = parse_contractual_penalty_terms(case_context)
    if contractual_terms is not None:
        _apply_contractual_penalty(
            case_context,
            draft,
            terms=contractual_terms,
            filing_date=filing_date,
            events=payments.payments,
        )
        return

    if not _research_has_article_353(research):
        _drop_article_353_lines(draft)
        _mark_penalty_for_verification(draft, CONTRACT_TERMS_MISSING_NOTE, case_context=case_context)
        _recompute_claim_price_and_duty(draft, case_context)
        return

    due_date = _extract_due_date(case_context)
    principal = _principal_amount(draft)
    if due_date is None or principal is None:
        _mark_penalty_for_verification(draft, DUE_DATE_MISSING_NOTE, case_context=case_context)
        _recompute_claim_price_and_duty(draft, case_context)
        return

    start = due_date + timedelta(days=1)
    if filing_date < start:
        reason = "На дату подачи иска срок исполнения ещё не наступил; неустойка по статье 353 не начисляется."
        _mark_penalty_for_verification(draft, reason, case_context=case_context)
        _recompute_claim_price_and_duty(draft, case_context)
        return

    if payments.payments:
        # Долг гасили частями: годовая ставка на весь период была бы начислена
        # на первоначальный долг и после платежей.
        _apply_article_353_by_intervals(
            case_context, draft, research=research, start=start, end=filing_date,
            principal=principal, events=payments.payments,
        )
        return

    old_penalty = _existing_penalty_amount(draft)
    old_price = parse_amount_kzt(draft.price_of_claim)
    penalty = calc_late_payment_penalty(
        principal,
        start,
        filing_date,
        rate_date=filing_date,
    )
    if penalty is None:
        draft.late_interest = needs_rate_marker(filing_date)
        _mark_penalty_for_verification(
            draft, rate_missing_note(filing_date), case_context=case_context
        )
        _recompute_claim_price_and_duty(draft, case_context)
        return

    _sync_calculated_penalty_narrative(
        draft,
        principal=principal,
        new_penalty=penalty.amount,
        old_penalty=old_penalty,
        old_price=old_price,
    )
    draft.requests = [item for item in draft.requests if not _PENALTY_LINE_RE.search(item)]
    draft.legal_basis = [item for item in draft.legal_basis if not _PENALTY_LINE_RE.search(item)]
    draft.legal_basis.append(
        "В соответствии с пунктами 1 и 2 статьи 353 Гражданского кодекса Республики Казахстан "
        "за неправомерное пользование чужими деньгами вследствие просрочки денежного обязательства "
        "подлежит уплате неустойка; при судебном взыскании кредитор вправе выбрать базовую ставку "
        "Национального Банка на день предъявления иска, вынесения решения либо фактического платежа, "
        "а неустойка начисляется по день уплаты суммы денег."
    )
    draft.late_interest = late_penalty_line(penalty)
    draft.requests.append(
        "Взыскать с ответчика в пользу истца неустойку по статье 353 ГК РК "
        f"в размере {format_kzt(penalty.amount)} за период {penalty.period()} "
        f"исходя из базовой ставки НБ РК {penalty.rate_percent:g}% на дату предъявления иска; "
        "за последующий период — по день фактической уплаты суммы долга в порядке статьи 353 ГК РК."
    )
    _recompute_claim_price_and_duty(draft, case_context)
    _write_deterministic_calculation(draft, late_interest_component(penalty))
    _enforce_calculation_gate(
        draft,
        _engine_reference(
            principal,
            penalty.start,
            penalty.end,
            PenaltyTerms(
                rate=penalty.rate_percent,
                rate_type=RateType.PER_YEAR,
                days_in_year=DAYS_IN_YEAR,
                legal_basis=ARTICLE_353_LABEL,
                legal_basis_source=ARTICLE_353_SOURCE_URL,
                rate_source=f"базовая ставка Национального Банка РК на {penalty.rate_date:%d.%m.%Y}",
            ),
        ),
        principal=principal,
        case_context=case_context,
    )


# Backwards compatibility: five production call sites and existing tests import
# the old function name. They now receive the generic penalty dispatcher.
_apply_verified_article_353 = _apply_verified_penalty


class ProductionOpenAILegalService(_BaseProductionOpenAILegalService):
    """Claude 353/citation idea adapted to the current source-bound runtime."""

    async def _targeted_article_353_research(
        self,
        case_context: str,
        language: str,
    ) -> tuple[list[str], list[str]]:
        """Verify Article 353 through the same actual-search-URL binding as KORGAN."""
        tools = [{
            "type": "web_search",
            "filters": {"allowed_domains": self.settings.legal_domains},
            "search_context_size": "low",
        }]
        prompt = (
            "Отдельная узкая проверка для денежного требования в иске. Открой действующую Общую часть "
            "Гражданского кодекса Республики Казахстан на Adilet (K940001000_) и проверь статью 353. "
            "Установи, применима ли она к описанной просрочке денежного обязательства. "
            "Если применима, верни один verified_point с точным выводом, article='353' и URL реально открытой "
            "официальной страницы. Если нет или источник не подтверждён — только unverified_claims.\n\n"
            f"МАТЕРИАЛЫ:\n{case_context[:24000]}"
        )
        payload, response = await self._structured_response(
            model=self.settings.openai_model,
            instructions=(
                "Ты source-bound юридический исследователь KORGAN. Не отвечай по памяти. "
                f"Язык: {'казахский' if language == 'kk' else 'русский'}."
            ),
            content=[{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
            schema_name="korgan_verified_legal_research",
            schema=_VERIFIED_RESEARCH_SCHEMA,
            tools=tools,
        )

        actual_urls = [
            url for url in _actual_response_urls(response)
            if self._is_current_official_source(url) and _GK_GENERAL_MARKER.lower() in url.lower()
        ]
        actual_by_canonical = {
            _canonical_url(url): url
            for url in actual_urls
            if _canonical_url(url)
        }
        claims: list[str] = []
        used_urls: list[str] = []
        for point in payload.get("verified_points", []):
            statement = str(point.get("statement", "")).strip()
            article = str(point.get("article", "")).strip()
            claimed_url = str(point.get("source_url", "")).strip()
            actual_url = actual_by_canonical.get(_canonical_url(claimed_url))
            if not statement or not _ARTICLE_353_RE.search(article) or not actual_url:
                continue
            claims.append(f"{statement} [основание: {article}; источник: {actual_url}]")
            if actual_url not in used_urls:
                used_urls.append(actual_url)
        return claims, used_urls

    async def research_case(self, case_context: str, language: str = "ru") -> LegalResearch:
        research = await super().research_case(case_context, language=language)
        if (
            not _explicit_penalty_requested(case_context)
            or parse_contractual_penalty_terms(case_context) is not None
            or _research_has_article_353(research)
        ):
            return research

        claims, urls = await self._targeted_article_353_research(case_context, language)
        for claim in claims:
            if claim not in research.verified_claims:
                research.verified_claims.append(claim)
        for url in urls:
            if url not in research.source_urls:
                research.source_urls.append(url)
        return research

    async def draft_claim(
        self,
        case_context: str,
        research: LegalResearch,
        language: str = "ru",
    ) -> ClaimDraft:
        draft = await super().draft_claim(case_context, research, language=language)
        _apply_verified_penalty(
            case_context,
            research,
            draft,
            filing_date=_today_kz(),
        )
        return draft
