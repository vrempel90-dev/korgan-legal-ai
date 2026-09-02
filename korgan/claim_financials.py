"""Детерминированное извлечение входных данных денежного расчёта.

Числа иска считает код, но считать их не из чего, пока исходные величины
берутся из прозы, которую написала модель. Прежний разбор так и работал:
``late_interest_hotfix._principal_amount`` читал сумму основного долга из
просительной части черновика, то есть из текста модели, и эта сумма
становилась базой неустойки, цены иска и госпошлины. Ошибка модели в одной
цифре проходила через весь расчёт, не встречая ни одной проверки: код честно
считал верную формулу от неверной базы.

Здесь входные величины извлекаются из МАТЕРИАЛОВ ДЕЛА — из того, что прислал
клиент, а не из того, что сочинил генератор. Разбор намеренно узкий и
fail-closed: две несовпадающие стоимости поставки, два разных срока оплаты или
расхождение между названным остатком долга и арифметикой платежей — это отказ
считать, а не выбор правдоподобного варианта.

Модуль не заменяет ``partial_payments`` и ``contractual_penalty``: он их
использует и достраивает там, где их разбор молча не срабатывал на боевых
формулировках — «0,1% от фактической просроченной задолженности» и «срок
оплаты по договору — до 10.03.2026».
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum

from korgan.contractual_penalty import parse_contractual_penalty_terms
from korgan.legal_calc import AMOUNT_PATTERN, parse_all_amounts_kzt
from korgan.partial_payments import find_partial_payments
from korgan.penalty_engine import PrincipalEvent

_MONTHS = {
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6,
    "июля": 7, "августа": 8, "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
}

_DATE_TOKEN = (
    r"(?:\d{1,2}[./-]\d{1,2}[./-]\d{4}|"
    r"\d{1,2}\s+(?:января|февраля|марта|апреля|мая|июня|июля|августа|"
    r"сентября|октября|ноября|декабря)\s+\d{4}(?:\s+года)?)"
)

_NUMBER = r"(?P<value>\d+(?:[.,]\d+)?)"
_PERCENT = r"(?:%|процент(?:а|ов)?\b)"

# Стоимость поставки/цена договора. Это база договорного предела неустойки и
# опорная величина для проверки заявленного остатка долга.
_CONTRACT_VALUE_RE = re.compile(
    r"(?:стоимост\w*\s+(?:поставк\w*|поставленн\w*\s+товар\w*|товар\w*|работ\w*|услуг\w*)"
    r"|цена\s+договора|сумма\s+договора|общая\s+стоимость\s+поставк\w*)"
    r"[^.\n]{0,60}?"
    r"(?P<amount>(?<!\d)(?<!\d[\s ])(?:\d{1,3}(?:[\s ]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?)"
    r"\s*(?:\([^)]*\)\s*)?(?:тенге|теңге|тг\b|₸|kzt))",
    re.IGNORECASE,
)

# Прямо названный остаток основного долга.
_PRINCIPAL_RE = re.compile(
    r"(?:остат\w*\s+(?:основн\w*\s+)?долг\w*|основн\w*\s+долг\w*|"
    r"сумма\s+(?:основного\s+)?долга|задолженност\w*)"
    r"[^.\n]{0,60}?"
    r"(?P<amount>(?<!\d)(?<!\d[\s ])(?:\d{1,3}(?:[\s ]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?)"
    r"\s*(?:\([^)]*\)\s*)?(?:тенге|теңге|тг\b|₸|kzt))",
    re.IGNORECASE,
)

# Срок оплаты. Существующий разбор в late_interest_hotfix знает только
# «вернуть/погасить … до DATE» и «срок оплаты истёк DATE»; боевая формулировка
# договора поставки — «срок оплаты по договору — до 10.03.2026» — мимо него
# проходила, и весь детерминированный расчёт неустойки не запускался.
_DUE_DATE_PATTERNS = (
    re.compile(
        rf"срок\s+(?:оплат\w*|платеж\w*|расч[её]т\w*|исполнени\w*)"
        rf"[^.\n]{{0,80}}?(?:не\s+позднее|до|по)\s+(?P<date>{_DATE_TOKEN})",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(?:оплатить|оплата|оплачен\w*|расч[её]т)\s*[^.\n]{{0,60}}?"
        rf"(?:должн\w*\s+быть\s+произведен\w*\s*)?(?:не\s+позднее|до)\s+(?P<date>{_DATE_TOKEN})",
        re.IGNORECASE,
    ),
    re.compile(
        rf"срок\s+(?:оплат\w*|платеж\w*)\s+(?:ист[её]к|наступил|был)[^\d]{{0,40}}(?P<date>{_DATE_TOKEN})",
        re.IGNORECASE,
    ),
)

# До какой даты считать неустойку, если клиент назвал её прямо.
_CALCULATION_END_RE = re.compile(
    rf"(?:расч[её]т\w*|начислен\w*|неустойк\w*|пен[яию])[^.\n]{{0,80}}?"
    rf"(?:по|до)\s+(?P<date>{_DATE_TOKEN})\s*(?:включительно)?",
    re.IGNORECASE,
)

# Ставка «за каждый день просрочки». Отличие от разбора в contractual_penalty —
# произвольное описание базы между процентом и «за каждый день»: договор пишет
# «от фактической просроченной задолженности», и точное совпадение со словом
# «задолженности» там не срабатывает.
_DAILY_RATE_RE = re.compile(
    rf"{_NUMBER}\s*{_PERCENT}\s*(?:от\s+[^.,;:\n]{{0,80}}?\s*)?"
    r"(?:за\s+кажд\w+\s+(?:календарн\w+\s+)?день(?:\s+просроч\w*)?|в\s+день)\b",
    re.IGNORECASE,
)

_CAP_RE = re.compile(
    rf"(?:но\s+)?(?:не\s+более|не\s+свыше|не\s+превыша\w*)\s*{_NUMBER}\s*{_PERCENT}"
    r"(?P<base>[^.;\n]{0,90})",
    re.IGNORECASE,
)

_CAP_BASE_CONTRACT_RE = re.compile(
    r"(?:первоначальн\w*\s+стоимост\w*|стоимост\w*\s+(?:поставленн\w*\s+)?товар\w*|"
    r"стоимост\w*\s+поставк\w*|сумм\w*\s+договора|цен\w*\s+договора)",
    re.IGNORECASE,
)
_CAP_BASE_DEBT_RE = re.compile(
    r"(?:сумм\w*\s+(?:основного\s+)?долга|задолженност\w*|основн\w*\s+долг\w*)",
    re.IGNORECASE,
)

_CLAUSE_RE = re.compile(r"(?:пункт(?:ом|у|а|е)?|п\.)\s*(?P<clause>\d+(?:\.\d+){1,3})", re.IGNORECASE)


class CapBase(StrEnum):
    """От чего договор считает предел неустойки."""

    #: От первоначальной стоимости поставки/цены договора.
    CONTRACT_VALUE = "contract_value"
    #: От суммы задолженности.
    DEBT = "debt"
    #: База не названа.
    UNSPECIFIED = "unspecified"


@dataclass(frozen=True, slots=True)
class CaseFinancials:
    """Входные величины расчёта, установленные по материалам дела."""

    #: Первоначальная стоимость поставки (цена договора).
    contract_value: int | None = None
    #: Остаток основного долга, названный в материалах прямо.
    stated_principal: int | None = None
    #: Остаток основного долга, выведенный из стоимости и платежей.
    derived_principal: int | None = None
    payments: tuple[PrincipalEvent, ...] = ()
    #: Частичная оплата упомянута, но её дату или размер установить не удалось.
    payments_unclear: bool = False
    penalty_rate_per_day: Decimal | None = None
    penalty_clause: str = ""
    cap_percent: Decimal | None = None
    cap_base: CapBase = CapBase.UNSPECIFIED
    due_date: date | None = None
    calculation_end: date | None = None
    #: Чего не хватило разбору. Пустой кортеж не означает полноту данных —
    #: только отсутствие обнаруженных противоречий.
    missing: tuple[str, ...] = ()

    @property
    def principal(self) -> int | None:
        """Остаток основного долга, если он установлен непротиворечиво.

        Названное клиентом значение и арифметика платежей проверяют друг друга.
        Расхождение между ними не разрешается в пользу одного из них: неизвестно,
        ошибся клиент в остатке или в перечне платежей, и обе версии одинаково
        правдоподобны.
        """
        stated = self.stated_principal
        derived = self.derived_principal
        if stated is not None and derived is not None:
            return stated if stated == derived else None
        return stated if stated is not None else derived

    @property
    def principal_conflict(self) -> bool:
        return (
            self.stated_principal is not None
            and self.derived_principal is not None
            and self.stated_principal != self.derived_principal
        )

    @property
    def cap_amount(self) -> int | None:
        """Предел неустойки в тенге, когда его база установлена.

        База предела — не деталь оформления: «10% первоначальной стоимости
        поставленного товара» и «10% суммы задолженности» дают разные числа,
        как только долг частично погашен. Пока база не установлена, предел в
        тенге не выводится.
        """
        if self.cap_percent is None:
            return None
        if self.cap_base is CapBase.CONTRACT_VALUE and self.contract_value is not None:
            return int(
                (Decimal(self.contract_value) * self.cap_percent / Decimal(100)).to_integral_value()
            )
        return None


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


def _single_amount(pattern: re.Pattern[str], text: str) -> tuple[int | None, bool]:
    """Единственная сумма, найденная по образцу. Второе значение — признак спора."""
    values: list[int] = []
    for match in pattern.finditer(text or ""):
        parsed = parse_all_amounts_kzt(match.group("amount"))
        if parsed and parsed[0] not in values:
            values.append(parsed[0])
    if len(values) == 1:
        return values[0], False
    return None, len(values) > 1


def _single_date(patterns: tuple[re.Pattern[str], ...], text: str) -> tuple[date | None, bool]:
    values: list[date] = []
    for pattern in patterns:
        for match in pattern.finditer(text or ""):
            parsed = _parse_date_token(match.group("date"))
            if parsed and parsed not in values:
                values.append(parsed)
    if len(values) == 1:
        return values[0], False
    return None, len(values) > 1


def _as_decimal(raw: str) -> Decimal | None:
    try:
        value = Decimal((raw or "").replace(",", "."))
    except (InvalidOperation, ValueError):
        return None
    return value if value > 0 else None


def _daily_rate(text: str) -> tuple[Decimal | None, bool]:
    values: list[Decimal] = []
    for match in _DAILY_RATE_RE.finditer(text or ""):
        value = _as_decimal(match.group("value"))
        if value is not None and value not in values:
            values.append(value)
    if len(values) == 1:
        return values[0], False
    return None, len(values) > 1


def _cap(text: str) -> tuple[Decimal | None, CapBase, bool]:
    found: list[tuple[Decimal, CapBase]] = []
    for match in _CAP_RE.finditer(text or ""):
        value = _as_decimal(match.group("value"))
        if value is None:
            continue
        tail = match.group("base") or ""
        if _CAP_BASE_CONTRACT_RE.search(tail):
            base = CapBase.CONTRACT_VALUE
        elif _CAP_BASE_DEBT_RE.search(tail):
            base = CapBase.DEBT
        else:
            base = CapBase.UNSPECIFIED
        if (value, base) not in found:
            found.append((value, base))
    if len(found) == 1:
        return found[0][0], found[0][1], False
    return None, CapBase.UNSPECIFIED, len(found) > 1


def _clause_near(text: str, position: int) -> str:
    preceding = [match for match in _CLAUSE_RE.finditer(text) if match.start() <= position]
    return preceding[-1].group("clause") if preceding else ""


def extract_case_financials(case_context: str) -> CaseFinancials:
    """Собрать входные величины расчёта из материалов дела."""
    text = str(case_context or "")
    missing: list[str] = []

    contract_value, contract_conflict = _single_amount(_CONTRACT_VALUE_RE, text)
    if contract_conflict:
        missing.append("в материалах названо несколько разных стоимостей поставки")

    stated_principal, principal_conflict = _single_amount(_PRINCIPAL_RE, text)
    if principal_conflict:
        missing.append("в материалах названо несколько разных сумм основного долга")

    scan = find_partial_payments(text)
    payments_unclear = bool(scan.mentioned and (scan.unparsed or not scan.payments))
    # Основание события попадает в таблицу расчёта, поэтому оно должно читаться
    # как строка таблицы, а не как выдержка из материалов. Полное предложение,
    # которым платёж описан у клиента, уже содержит сумму, и в таблице она
    # печаталась дважды — второй раз без разрядов.
    payments = tuple(
        replace(event, basis=f"частичная оплата от {event.on:%d.%m.%Y}")
        for event in scan.payments
    )
    if payments_unclear:
        missing.append("частичная оплата упомянута, но её дату или размер установить не удалось")

    derived_principal: int | None = None
    if contract_value is not None and not payments_unclear:
        paid = sum(-int(event.delta) for event in scan.payments if int(event.delta) < 0)
        candidate = contract_value - paid
        if candidate > 0:
            derived_principal = candidate

    rate, rate_conflict = _daily_rate(text)
    if rate_conflict:
        missing.append("в материалах названо несколько разных ставок неустойки за день просрочки")

    clause = ""
    if rate is not None:
        terms = parse_contractual_penalty_terms(text)
        if terms is not None and terms.clause:
            clause = terms.clause
        else:
            match = _DAILY_RATE_RE.search(text)
            if match:
                clause = _clause_near(text, match.start())

    cap_percent, cap_base, cap_conflict = _cap(text)
    if cap_conflict:
        missing.append("в материалах названо несколько разных пределов неустойки")

    due_date, due_conflict = _single_date(_DUE_DATE_PATTERNS, text)
    if due_conflict:
        missing.append("в материалах названо несколько разных сроков оплаты")

    calculation_end, end_conflict = _single_date((_CALCULATION_END_RE,), text)
    if end_conflict:
        missing.append("в материалах названо несколько разных дат окончания расчёта")

    financials = CaseFinancials(
        contract_value=contract_value,
        stated_principal=stated_principal,
        derived_principal=derived_principal,
        payments=payments,
        payments_unclear=payments_unclear,
        penalty_rate_per_day=rate,
        penalty_clause=clause,
        cap_percent=cap_percent,
        cap_base=cap_base,
        due_date=due_date,
        calculation_end=calculation_end,
        missing=tuple(missing),
    )

    if financials.principal_conflict:
        return CaseFinancials(
            contract_value=contract_value,
            stated_principal=stated_principal,
            derived_principal=derived_principal,
            payments=payments,
            payments_unclear=payments_unclear,
            penalty_rate_per_day=rate,
            penalty_clause=clause,
            cap_percent=cap_percent,
            cap_base=cap_base,
            due_date=due_date,
            calculation_end=calculation_end,
            missing=(
                *missing,
                f"названный остаток основного долга {stated_principal} тенге не сходится "
                f"со стоимостью поставки за вычетом подтверждённых платежей "
                f"({derived_principal} тенге)",
            ),
        )
    return financials
