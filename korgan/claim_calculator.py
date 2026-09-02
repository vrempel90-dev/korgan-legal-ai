"""Единственный источник числовых полей искового заявления.

Что здесь происходит
--------------------
Модуль собирает один структурированный результат расчёта из входных величин,
установленных по материалам дела (``claim_financials``), и записывает его в
черновик. Записывает — единственный: цена иска, госпошлина, основной долг,
неустойка и раздел расчёта после этого приходят из одного места и по
построению не могут разойтись между шапкой, расчётом и просительной частью.

Почему авторство берётся не всегда
----------------------------------
Расчёт покрывает денежные требования, которые выводятся арифметически: долг,
неустойка, цена иска, пошлина. Иск может содержать и другие денежные
требования — убытки, моральный вред, упущенную выгоду, — которые из материалов
не выводятся вовсе. Тогда модуль отказывается от авторства целиком и возвращает
управление прежнему пути: посчитать часть суммы и промолчать про остальную
хуже, чем не считать, потому что итог всё равно окажется неверным, но выглядеть
будет посчитанным.

Отказ считать — это ``INSUFFICIENT_DATA`` в структуре результата и сообщение
юристу, а не фраза в судебном тексте. Поле остаётся пустым, требование
снимается, и решение принимает человек.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from korgan.claim_calculation_contract import (
    ClaimCalculation,
    FieldStatus,
    calculated,
    insufficient,
    not_applicable,
)
from korgan.claim_financials import CapBase, CaseFinancials, extract_case_financials
from korgan.legal_calc import (
    calc_gosposhlina_claim,
    claimant_is_individual,
    format_kzt,
    gosposhlina_line,
)
from korgan.legal_calculation import interval_penalty_component, principal_component, render_calculation
from korgan.legal_types import ClaimDraft
from korgan.penalty_engine import (
    CalculationStatus,
    PenaltyCalculation,
    PenaltyTerms,
    RateType,
    calculate_penalty,
)

# Классификация строк просительной части. Регулярные выражения повторяют те,
# по которым уже работает боевой разбор в late_interest_hotfix: разойдись они —
# и одна и та же строка считалась бы неустойкой в одном месте и долгом в другом.
_PENALTY_RE = re.compile(
    r"(?:ст\.?\s*353|стать\w*\s*353|неустойк\w*|пен[яию]\b|штраф\w*|өсімпұл\w*|"
    r"тұрақсыздық\s+айыб\w*|пользован\w*\s+чужими\s+деньг\w*|"
    r"процент\w*\s+(?:по\s+денежн\w*|за\s+просроч\w*))",
    re.IGNORECASE,
)
_STATE_DUTY_OR_COST_RE = re.compile(
    r"(?:государственн\w*\s+пошлин\w*|госпошлин\w*|судебн\w*\s+(?:расход\w*|издерж\w*)|"
    r"расход\w*\s+на\s+(?:оплат\w*\s+)?представител\w*)",
    re.IGNORECASE,
)
_PRINCIPAL_RE = re.compile(
    r"(?:основн\w*\s+долг\w*|задолженн\w*|долг\w*|негізгі\s+берешек|берешек\w*|қарыз\w*)",
    re.IGNORECASE,
)
_MONEY_TOKEN_RE = re.compile(
    r"(?<!\d)\d[\d\s ]*(?:[.,]\d{1,2})?\s*(?:тенге|теңге|тг\b|₸|kzt)",
    re.IGNORECASE,
)
_MONEY_INTENT_RE = re.compile(
    r"(?:убыт\w*|ущерб\w*|моральн\w*\s+вред\w*|упущенн\w*\s+выгод\w*|компенсац\w*|"
    r"неоснователь\w*\s+обогащ\w*|проценты\s+за\s+пользован\w*\s+займ\w*)",
    re.IGNORECASE,
)

PRINCIPAL_KEY = "principal"
PENALTY_KEY = "penalty"
CLAIM_PRICE_KEY = "claim_price"
STATE_DUTY_KEY = "state_duty"
TOTAL_CLAIM_KEY = "total_claim"


@dataclass(frozen=True, slots=True)
class CalculatorOutcome:
    """Результат расчёта вместе с деталями, нужными для записи в документ."""

    calculation: ClaimCalculation
    penalty: PenaltyCalculation | None
    financials: CaseFinancials


def _penalty_terms(financials: CaseFinancials) -> tuple[PenaltyTerms | None, tuple[str, ...]]:
    """Условие об ответственности в терминах ``penalty_engine``.

    Предел переводится в тенге заранее, когда договор считает его от
    первоначальной стоимости поставки: движок применяет процентный предел к
    остатку долга на начало периода, а это другая база и другое число, как
    только долг гасили частями.
    """
    rate = financials.penalty_rate_per_day
    if rate is None:
        return None, ("в материалах не установлена ставка договорной неустойки за день просрочки",)

    clause = f"пункт {financials.penalty_clause} договора" if financials.penalty_clause else "условие договора о неустойке"

    cap_amount: int | None = None
    cap_percent: Decimal | None = None
    if financials.cap_percent is not None:
        if financials.cap_base is CapBase.CONTRACT_VALUE:
            cap_amount = financials.cap_amount
            if cap_amount is None:
                return None, (
                    "договорный предел неустойки считается от первоначальной стоимости поставки, "
                    "а сама стоимость в материалах не установлена",
                )
        elif financials.cap_base is CapBase.DEBT:
            cap_percent = financials.cap_percent
        else:
            return None, (
                f"договор ограничивает неустойку {financials.cap_percent:g}%, но не сказано, "
                "от какой базы считается этот предел",
            )

    return (
        PenaltyTerms(
            rate=rate,
            rate_type=RateType.PER_DAY,
            contract_basis=clause,
            # Ставку и предел извлёк один и тот же fail-closed разбор договора:
            # подтверждены они ровно в одинаковой мере.
            rate_source=clause,
            cap_amount=cap_amount,
            cap_percent=cap_percent,
            cap_verified=cap_amount is not None or cap_percent is not None,
        ),
        (),
    )


def _penalty_base(financials: CaseFinancials) -> tuple[int | None, tuple[str, ...]]:
    """Долг на начало просрочки — база первого интервала начисления.

    При частичном погашении начислять от остатка нельзя: до платежа долг был
    больше, и неустойка за этот отрезок считается от прежней суммы. Поэтому,
    когда платежи есть, обязательна первоначальная стоимость поставки, а
    платежи передаются движку событиями.
    """
    if financials.payments:
        if financials.contract_value is None:
            return None, (
                "долг гасили частями, а первоначальная стоимость поставки в материалах "
                "не установлена: начислять неустойку не от чего",
            )
        return financials.contract_value, ()
    principal = financials.principal
    if principal is None:
        return None, ("не установлена сумма основного долга",)
    return principal, ()


def build_claim_calculation(
    case_context: str,
    financials: CaseFinancials,
    *,
    filing_date: date,
    penalty_claimed: bool,
) -> CalculatorOutcome:
    """Собрать структурированный расчёт денежных требований иска."""
    notes: list[str] = list(financials.missing)

    principal_value = financials.principal
    if principal_value is None:
        principal_field = insufficient(
            PRINCIPAL_KEY,
            *(financials.missing or ("не установлена сумма основного долга",)),
        )
    else:
        parts = []
        if financials.contract_value is not None:
            parts.append(f"стоимость поставки {format_kzt(financials.contract_value)}")
        for event in financials.payments:
            parts.append(f"платёж {event.on:%d.%m.%Y} {format_kzt(abs(int(event.delta)))}")
        principal_field = calculated(
            PRINCIPAL_KEY,
            principal_value,
            source="; ".join(parts) or "остаток долга по материалам дела",
            breakdown=tuple(parts),
        )

    penalty_calculation: PenaltyCalculation | None = None
    if not penalty_claimed:
        penalty_field = not_applicable(PENALTY_KEY, source="требование о неустойке не заявлено")
    elif financials.payments_unclear:
        penalty_field = insufficient(
            PENALTY_KEY,
            "частичная оплата упомянута, но её дату или размер установить не удалось",
        )
    elif financials.due_date is None:
        penalty_field = insufficient(
            PENALTY_KEY, "в материалах не установлен срок оплаты, с которого начинается просрочка"
        )
    else:
        terms, reasons = _penalty_terms(financials)
        base, base_reasons = _penalty_base(financials)
        if terms is None or base is None:
            penalty_field = insufficient(PENALTY_KEY, *(reasons + base_reasons))
        else:
            start = financials.due_date + timedelta(days=1)
            end = financials.calculation_end or filing_date
            if end < start:
                penalty_field = not_applicable(
                    PENALTY_KEY, source="на дату расчёта просрочка ещё не наступила"
                )
            else:
                penalty_calculation = calculate_penalty(
                    base, start, end, terms, events=financials.payments, breach="просрочка оплаты"
                )
                if penalty_calculation.status is not CalculationStatus.CALCULATED:
                    penalty_field = insufficient(
                        PENALTY_KEY, *(penalty_calculation.reasons or ("расчёт неустойки не выполнен",))
                    )
                    penalty_calculation = None
                else:
                    cap_note = ()
                    if penalty_calculation.capped and penalty_calculation.cap_amount is not None:
                        cap_note = (
                            f"начислено {format_kzt(penalty_calculation.raw_total)}, "
                            f"предъявлено в пределах договорного ограничения "
                            f"{format_kzt(penalty_calculation.cap_amount)}",
                        )
                    penalty_field = calculated(
                        PENALTY_KEY,
                        penalty_calculation.total,
                        source=terms.basis,
                        breakdown=tuple(
                            f"{i.period_from:%d.%m.%Y}—{i.period_to:%d.%m.%Y}: "
                            f"{format_kzt(i.principal)} × {i.rate:g}% × {i.days} дн. "
                            f"= {format_kzt(i.subtotal)}"
                            for i in penalty_calculation.intervals
                        )
                        + cap_note,
                    )

    if principal_field.ready and penalty_field.status is not FieldStatus.INSUFFICIENT_DATA:
        price_value = int(principal_field.value or 0) + int(penalty_field.value or 0)
        claim_price_field = calculated(
            CLAIM_PRICE_KEY,
            price_value,
            source="основной долг" + (" + неустойка" if penalty_field.ready else ""),
            breakdown=tuple(
                part
                for part in (
                    f"основной долг {principal_field.display}",
                    f"неустойка {penalty_field.display}" if penalty_field.ready else "",
                )
                if part
            ),
        )
    else:
        reasons = tuple(principal_field.missing) + tuple(penalty_field.missing)
        claim_price_field = insufficient(
            CLAIM_PRICE_KEY, *(reasons or ("не все денежные требования разрешены в числа",))
        )

    is_individual = claimant_is_individual(case_context)
    if not claim_price_field.ready:
        duty_field = insufficient(STATE_DUTY_KEY, "цена иска не определена")
    elif is_individual is None:
        duty_field = insufficient(
            STATE_DUTY_KEY,
            "по материалам нельзя установить, является ли истец физическим или юридическим лицом",
        )
    else:
        try:
            duty_value = calc_gosposhlina_claim(int(claim_price_field.value or 0), is_individual)
        except RuntimeError as exc:
            duty_field = insufficient(STATE_DUTY_KEY, str(exc))
        else:
            duty_field = calculated(
                STATE_DUTY_KEY,
                duty_value,
                source=(
                    "статья 665 Налогового кодекса РК; "
                    + ("1% для физического лица" if is_individual else "3% для юридического лица")
                ),
                breakdown=(f"цена иска {claim_price_field.display}",),
            )

    if claim_price_field.ready and duty_field.ready:
        total_field = calculated(
            TOTAL_CLAIM_KEY,
            int(claim_price_field.value or 0) + int(duty_field.value or 0),
            source="цена иска + возмещаемая госпошлина",
            breakdown=(
                f"цена иска {claim_price_field.display}",
                f"госпошлина {duty_field.display}",
            ),
        )
    else:
        total_field = insufficient(
            TOTAL_CLAIM_KEY, *(claim_price_field.missing or duty_field.missing or ("итог не выводится",))
        )

    calculation = ClaimCalculation(
        principal=principal_field,
        penalty=penalty_field,
        claim_price=claim_price_field,
        state_duty=duty_field,
        total_claim=total_field,
        lawyer_notes=tuple(dict.fromkeys(notes)),
        inputs={
            "contract_value": financials.contract_value,
            "stated_principal": financials.stated_principal,
            "derived_principal": financials.derived_principal,
            "payments": [
                {"on": event.on.isoformat(), "amount": abs(int(event.delta))}
                for event in financials.payments
            ],
            "rate_percent_per_day": (
                str(financials.penalty_rate_per_day) if financials.penalty_rate_per_day is not None else None
            ),
            "cap_percent": str(financials.cap_percent) if financials.cap_percent is not None else None,
            "cap_base": str(financials.cap_base),
            "cap_amount": financials.cap_amount,
            "due_date": financials.due_date.isoformat() if financials.due_date else None,
            "calculation_end": (
                financials.calculation_end.isoformat() if financials.calculation_end else None
            ),
        },
    )
    return CalculatorOutcome(calculation=calculation, penalty=penalty_calculation, financials=financials)


def substitute_placeholders(draft: ClaimDraft, calculation: ClaimCalculation) -> None:
    """Подставить рассчитанные суммы вместо плейсхолдеров модели.

    Модель обозначает денежную сумму токеном и никогда не пишет её сама.
    Подстановка идёт по всем текстовым полям черновика: сумма, названная в
    фактической части, обязана совпасть с суммой из просительной, а совпасть
    они могут только если обе получены отсюда.
    """
    mapping = calculation.placeholders()
    if not mapping:
        return

    def apply(text: str) -> str:
        for token, value in mapping.items():
            text = text.replace(token, value)
        return text

    draft.title = apply(draft.title or "")
    draft.price_of_claim = apply(draft.price_of_claim or "")
    draft.late_interest = apply(draft.late_interest or "")
    draft.jurisdiction_reason = apply(draft.jurisdiction_reason or "")
    for name in ("facts", "legal_basis", "requests", "attachments", "calculation", "motions"):
        values = getattr(draft, name, None)
        if isinstance(values, list):
            setattr(draft, name, [apply(str(item)) for item in values])


#: Незамещённый плейсхолдер. Модель обозначает им сумму, а подставляет её
#: расчёт; дожить до документа токен не может ни при каком исходе.
_PLACEHOLDER_RE = re.compile(r"\{\{\s*[a-z_]+\s*\}\}", re.IGNORECASE)


def strip_unresolved_placeholders(draft: ClaimDraft) -> tuple[str, ...]:
    """Убрать из черновика суммы, которые так и не были рассчитаны.

    Плейсхолдер остаётся незамещённым ровно тогда, когда расчёт этого поля не
    состоялся. Печатать «{{principal_amount}}» в иске нельзя, а подставлять
    вместо него число модели — тем более: именно от этого числа модуль и
    защищает. Строка требования снимается целиком, и почему она снята, читает
    юрист.

    Заголовок обрабатывается иначе: он не утверждает сумму как требование, и
    иск без цифры в названии остаётся нормальным иском.
    """
    removed: list[str] = []

    for name in ("facts", "legal_basis", "requests", "attachments", "calculation", "motions"):
        values = getattr(draft, name, None)
        if not isinstance(values, list):
            continue
        kept = []
        for item in values:
            text = str(item)
            if _PLACEHOLDER_RE.search(text):
                removed.append(f"из раздела «{name}» снята строка без рассчитанной суммы: {text.strip()}")
                continue
            kept.append(text)
        setattr(draft, name, kept)

    for name in ("price_of_claim", "late_interest", "jurisdiction_reason"):
        text = str(getattr(draft, name, "") or "")
        if _PLACEHOLDER_RE.search(text):
            removed.append(f"поле «{name}» оставлено незаполненным: сумма не рассчитана")
            setattr(draft, name, "")

    title = str(draft.title or "")
    if _PLACEHOLDER_RE.search(title):
        draft.title = " ".join(_PLACEHOLDER_RE.sub("", title).split()).strip(" ,;—-")

    return tuple(removed)


def _request_kind(request: str) -> str:
    text = str(request or "")
    if _STATE_DUTY_OR_COST_RE.search(text):
        return "cost"
    if _PENALTY_RE.search(text):
        return "penalty"
    if _MONEY_INTENT_RE.search(text):
        return "other_money"
    if _PRINCIPAL_RE.search(text):
        return "principal"
    if _MONEY_TOKEN_RE.search(text):
        return "other_money"
    return "nonmoney"


def claim_is_debt_and_penalty_only(draft: ClaimDraft) -> bool:
    """Покрывает ли расчёт все денежные требования просительной части."""
    return not any(_request_kind(item) == "other_money" for item in (draft.requests or []))


#: Итоговая сводка просительной части. Она не самостоятельное требование, а
#: сумма уже перечисленных, поэтому обратный разбор просительной части обязан
#: её пропустить, а не сложить с компонентами.
_TOTAL_SUMMARY_RE = re.compile(
    r"общая\s+сумма\s+ко\s+взысканию", re.IGNORECASE
)


def _total_summary(calculation: ClaimCalculation) -> str:
    """Строка с итоговой суммой взыскания — та, которую читает клиент.

    Просительная часть без явного итога заставляет читателя складывать
    требования самому, и первым это делает суд. Упоминание госпошлины внутри
    строки не случайно: по нему обратный разбор просительной части опознаёт
    сводку и не считает её ещё одним требованием — тем самым цена иска не
    удваивается.
    """
    if not (calculation.total_claim.ready and calculation.claim_price.ready and calculation.state_duty.ready):
        return ""
    return (
        f"Общая сумма ко взысканию с ответчика составляет {calculation.total_claim.display}, "
        f"включая цену иска {calculation.claim_price.display} и возмещение "
        f"государственной пошлины {calculation.state_duty.display}."
    )


def _principal_request(calculation: ClaimCalculation) -> str:
    return (
        "Взыскать с ответчика в пользу истца основной долг в размере "
        f"{calculation.principal.display}."
    )


def _penalty_request(calculation: ClaimCalculation, penalty: PenaltyCalculation, clause: str) -> str:
    first = penalty.intervals[0]
    last = penalty.intervals[-1]
    basis = f"по {clause}" if clause else "по условию договора о неустойке"
    return (
        f"Взыскать с ответчика в пользу истца договорную неустойку {basis} в размере "
        f"{calculation.penalty.display} за период с {first.period_from:%d.%m.%Y} "
        f"по {last.period_to:%d.%m.%Y}."
    )


def apply_claim_calculation(
    draft: ClaimDraft,
    outcome: CalculatorOutcome,
    *,
    case_context: str,
) -> bool:
    """Записать расчёт в черновик как единственный источник его чисел.

    Возвращает ``True``, если авторство над числами взято полностью. ``False``
    означает, что расчёт покрывает не все денежные требования иска, и вызывающая
    сторона обязана продолжить прежним путём: половина чисел из калькулятора и
    половина из текста модели — это ровно то расхождение, ради устранения
    которого модуль написан.
    """
    calculation = outcome.calculation
    substitute_placeholders(draft, calculation)

    if not claim_is_debt_and_penalty_only(draft):
        return False
    if not calculation.claim_price.ready:
        return False

    clause = (
        f"пункту {outcome.financials.penalty_clause} договора"
        if outcome.financials.penalty_clause
        else ""
    )

    kept = [
        item
        for item in (draft.requests or [])
        if _request_kind(item) in {"cost", "nonmoney"} and not _TOTAL_SUMMARY_RE.search(str(item))
    ]
    money_requests = [_principal_request(calculation)]
    if calculation.penalty.ready and outcome.penalty is not None:
        money_requests.append(_penalty_request(calculation, outcome.penalty, clause))
    draft.requests = money_requests + kept
    summary = _total_summary(calculation)
    if summary:
        draft.requests.append(summary)

    draft.price_of_claim = calculation.claim_price.display
    draft.state_duty = gosposhlina_line(case_context, draft.price_of_claim)

    components = [principal_component(int(calculation.principal.value or 0), basis="")]
    if calculation.penalty.ready and outcome.penalty is not None:
        components.append(
            interval_penalty_component(
                outcome.penalty,
                title="Договорная неустойка",
                basis=clause.replace("пункту", "пункт") or "условие договора о неустойке",
                rate_label=(
                    f"{outcome.financials.penalty_rate_per_day:g}% за каждый день просрочки"
                    if outcome.financials.penalty_rate_per_day is not None
                    else ""
                ),
            )
        )
        draft.late_interest = components[-1].render()
    else:
        draft.late_interest = ""

    lines = render_calculation(components)
    if calculation.state_duty.ready and calculation.total_claim.ready:
        lines.append(f"Государственная пошлина: {calculation.state_duty.display}.")
        lines.append(f"Итого ко взысканию с ответчика: {calculation.total_claim.display}.")
    draft.calculation = lines

    if clause:
        rate = outcome.financials.penalty_rate_per_day
        basis_line = (
            f"Пунктом {outcome.financials.penalty_clause} договора предусмотрена договорная неустойка"
            + (f" в размере {rate:g}% за каждый день просрочки" if rate is not None else "")
            + "; при частичном погашении долга неустойка начисляется на остаток задолженности."
        )
        draft.legal_basis = [item for item in draft.legal_basis if not _PENALTY_RE.search(item)]
        if calculation.penalty.ready:
            draft.legal_basis.append(basis_line)
    return True


def try_calculator_authority(
    case_context: str,
    draft: ClaimDraft,
    *,
    filing_date: date,
    penalty_claimed: bool,
) -> CalculatorOutcome | None:
    """Взять числа иска на детерминированный расчёт, если это возможно.

    ``None`` означает, что расчёт не покрывает дело целиком и прежний путь
    обязан отработать без изменений. Частичное авторство здесь не бывает.
    """
    financials = extract_case_financials(case_context)
    outcome = build_claim_calculation(
        case_context, financials, filing_date=filing_date, penalty_claimed=penalty_claimed
    )
    if not outcome.calculation.claim_price.ready:
        return None
    if not apply_claim_calculation(draft, outcome, case_context=case_context):
        return None
    return outcome
