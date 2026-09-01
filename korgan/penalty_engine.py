"""Детерминированный расчёт неустойки, пени и штрафа.

Арифметику денежного требования выполняет этот модуль, а не языковая модель.
Модель устанавливает правовое основание, извлекает исходные данные и определяет
период; сумму считает код. Причина не в недоверии к модели вообще, а в том, что
сумма из просительной части иска проверяется судом и противной стороной
вручную, и разойтись она не имеет права ни на тенге.

Три вещи, которые модуль делает принципиально иначе прежнего расчёта:

* **Интервалы.** При частичном погашении неустойка не считается от
  первоначального долга до конца периода. Период разбивается по датам
  изменения долга, и каждый интервал считается от своего остатка.
* **Типы ставок.** Договор задаёт ставку в день, в месяц, годовых, фиксированной
  суммой или процентом от обязательства. Проценты в день и годовые отличаются
  в сотни раз, и подстановка не того типа не выглядит ошибкой в тексте.
* **Отказ вместо догадки.** Неподтверждённое основание, неподтверждённый лимит,
  погашенный долг — это ``NEEDS_VERIFICATION`` с названной причиной, а не
  правдоподобное число.

Модуль ничего не парсит из текста дела: исходные данные ему передают уже
установленными. Разбор договорной формулировки живёт в ``contractual_penalty``.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from enum import StrEnum

_HUNDRED = Decimal(100)


class RateType(StrEnum):
    """Как договор или закон выражает размер ответственности."""

    #: Фиксированная сумма штрафа. ``rate`` — тенге, а не проценты.
    FIXED = "fixed"
    #: Процент за каждый день просрочки. 0,1% в день — это ``Decimal("0.1")``.
    PER_DAY = "percent_per_day"
    #: Процент за месяц просрочки; неполный месяц считается по его дням.
    PER_MONTH = "percent_per_month"
    #: Процент годовых. Так выражена и законная неустойка статьи 353 ГК РК.
    PER_YEAR = "percent_per_year"
    #: Однократный процент от базы, без привязки к длительности просрочки.
    PERCENT_OF_OBLIGATION = "percent_of_obligation"


class CalculationStatus(StrEnum):
    CALCULATED = "calculated"
    NEEDS_VERIFICATION = "needs_verification"


def _decimal(value: Decimal | int | float | str) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _round_tenge(value: Decimal) -> int:
    """Округлить до целого тенге, половину — вверх.

    Встроенный ``round`` округляет ровно половину к чётному, а бухгалтерский и
    судебный расчёт округляет её вверх. Разница в один тенге в просительной
    части — это расхождение с перепроверкой, которое придётся объяснять.
    """
    return int(value.to_integral_value(rounding=ROUND_HALF_UP))


@dataclass(frozen=True, slots=True)
class PrincipalEvent:
    """Подтверждённое изменение суммы обязательства.

    Событие действует С СВОЕЙ ДАТЫ включительно: день платежа считается уже по
    уменьшенному остатку. Если договор считает иначе, дату сдвигает вызывающая
    сторона — угадывать это здесь нечем.
    """

    on: date
    #: Отрицательная — погашение, зачёт, возврат; положительная — доначисление.
    delta: int
    #: Чем изменение подтверждено: платёжное поручение, акт, соглашение.
    basis: str = ""
    kind: str = "payment"

    def __post_init__(self) -> None:
        if not isinstance(self.on, date):
            raise ValueError("Дата изменения суммы обязательства должна быть датой")
        if int(self.delta) == 0:
            raise ValueError("Изменение суммы обязательства не может быть нулевым")


@dataclass(frozen=True, slots=True)
class PenaltyTerms:
    """Условие об ответственности — уже установленное, а не предполагаемое."""

    rate: Decimal
    rate_type: RateType
    #: Норма закона, если неустойка законная.
    legal_basis: str = ""
    #: Официальный источник нормы. Память модели источником права не является:
    #: статью нельзя поставить в документ только потому, что модель её «знает».
    legal_basis_source: str = ""
    #: Пункт договора, если неустойка договорная.
    contract_basis: str = ""
    #: Откуда взят сам размер ставки. Пустое значение закрывает расчёт: ставка
    #: без источника — это предположение, а по нему взыскивают деньги.
    rate_source: str = ""
    #: Какое нарушение покрывает условие: просрочка оплаты, просрочка поставки,
    #: непредоставление документов. Пункт про одно нарушение к другому не
    #: применяется, а в тексте договора эти пункты выглядят одинаково.
    breach: str = ""
    #: Предел в тенге либо в процентах от базы. Одновременно — не бывает.
    cap_amount: int | None = None
    cap_percent: Decimal | None = None
    #: Предел применяется, только когда он подтверждён договором или законом.
    cap_verified: bool = False
    days_in_year: int = 365

    def __post_init__(self) -> None:
        object.__setattr__(self, "rate", _decimal(self.rate))
        if self.cap_percent is not None:
            object.__setattr__(self, "cap_percent", _decimal(self.cap_percent))
        if self.rate <= 0:
            raise ValueError("Размер неустойки должен быть положительным")
        if self.days_in_year <= 0:
            raise ValueError("Число дней в году должно быть положительным")
        if self.cap_amount is not None and self.cap_percent is not None:
            raise ValueError("Предел неустойки задан дважды — в тенге и в процентах")
        if self.cap_amount is not None and self.cap_amount <= 0:
            raise ValueError("Предел неустойки должен быть положительным")
        if self.cap_percent is not None and self.cap_percent <= 0:
            raise ValueError("Предел неустойки должен быть положительным")

    @property
    def has_basis(self) -> bool:
        return bool(self.legal_basis.strip() or self.contract_basis.strip())

    @property
    def basis(self) -> str:
        return self.contract_basis.strip() or self.legal_basis.strip()


@dataclass(frozen=True, slots=True)
class PenaltyInterval:
    """Строка таблицы расчёта: один остаток долга на одном отрезке времени."""

    period_from: date
    period_to: date
    days: int
    principal: int
    rate: Decimal
    rate_type: RateType
    subtotal: int
    formula: str
    #: Что закончило отрезок: платёж, доначисление, конец периода.
    event_ending_period: str = ""

    def period(self) -> str:
        return f"{self.period_from.strftime('%d.%m.%Y')}—{self.period_to.strftime('%d.%m.%Y')}"


@dataclass(frozen=True, slots=True)
class PenaltyCalculation:
    status: CalculationStatus
    intervals: tuple[PenaltyInterval, ...] = ()
    #: Сумма до применения предела.
    raw_total: int = 0
    #: Итог требования: с применённым подтверждённым пределом.
    total: int = 0
    cap_amount: int | None = None
    capped: bool = False
    #: Сумма, которую назвал клиент, если он её называл.
    claimed_amount: int | None = None
    reasons: tuple[str, ...] = ()
    terms: PenaltyTerms | None = None

    @property
    def ready(self) -> bool:
        return self.status is CalculationStatus.CALCULATED

    @property
    def claim_matches(self) -> bool | None:
        """Совпал ли расчёт клиента с расчётом системы.

        ``None`` — клиент суммы не называл. ``False`` — назвал, и она другая;
        в документ идёт сумма системы, а расхождение выносится юристу.
        """
        if self.claimed_amount is None:
            return None
        return self.claimed_amount == self.total

    def table(self) -> list[dict[str, object]]:
        """Таблица расчёта — та самая, что попадает в документ."""
        return [
            {
                "period_from": interval.period_from,
                "period_to": interval.period_to,
                "days": interval.days,
                "principal": interval.principal,
                "rate": interval.rate,
                "formula": interval.formula,
                "subtotal": interval.subtotal,
                "event_ending_period": interval.event_ending_period,
            }
            for interval in self.intervals
        ]


def _needs(reason: str, *more: str, terms: PenaltyTerms | None = None,
           claimed_amount: int | None = None) -> PenaltyCalculation:
    return PenaltyCalculation(
        status=CalculationStatus.NEEDS_VERIFICATION,
        reasons=(reason, *more),
        terms=terms,
        claimed_amount=claimed_amount,
    )


def _balance_timeline(
    principal: int, start: date, end: date, events: tuple[PrincipalEvent, ...]
) -> list[tuple[date, date, int, str]]:
    """Отрезки постоянного остатка долга внутри периода просрочки.

    События до начала периода уменьшают или увеличивают начальный остаток — долг
    мог частично гаситься ещё до просрочки. События после конца периода не
    учитываются: они не влияли на просрочку, за которую заявлено требование.
    """
    opening = principal + sum(int(e.delta) for e in events if e.on < start)
    inside = sorted(
        (e for e in events if start <= e.on <= end),
        key=lambda e: (e.on, e.kind, e.basis),
    )

    segments: list[tuple[date, date, int, str]] = []
    balance = opening
    cursor = start
    index = 0
    while index < len(inside):
        moment = inside[index].on
        same_day = [e for e in inside[index:] if e.on == moment]
        index += len(same_day)
        label = "; ".join(
            f"{e.basis or e.kind} {abs(int(e.delta))} тенге" for e in same_day
        )
        if moment > cursor:
            segments.append((cursor, moment - timedelta(days=1), balance, label))
        balance += sum(int(e.delta) for e in same_day)
        cursor = moment

    if cursor <= end:
        segments.append((cursor, end, balance, ""))
    return segments


def _split_calendar_months(period_from: date, period_to: date) -> list[tuple[date, date]]:
    """Разрезать отрезок по календарным месяцам.

    Месячная ставка иначе не считается честно: в феврале и в марте разное число
    дней, и «месяц» из середины одного месяца в середину другого — не месяц.
    """
    parts: list[tuple[date, date]] = []
    cursor = period_from
    while cursor <= period_to:
        last_day = calendar.monthrange(cursor.year, cursor.month)[1]
        month_end = date(cursor.year, cursor.month, last_day)
        parts.append((cursor, min(month_end, period_to)))
        cursor = month_end + timedelta(days=1)
    return parts


def _interval_amount(
    principal: int, days: int, period_from: date, period_to: date, terms: PenaltyTerms
) -> tuple[Decimal, str]:
    rate = terms.rate
    base = Decimal(principal)
    if terms.rate_type is RateType.PER_DAY:
        fraction = rate / _HUNDRED
        return base * fraction * Decimal(days), (
            f"{principal} × {rate:g}% × {days} дн."
        )
    if terms.rate_type is RateType.PER_YEAR:
        fraction = rate / _HUNDRED
        return base * fraction * Decimal(days) / Decimal(terms.days_in_year), (
            f"{principal} × {rate:g}% × {days} дн. / {terms.days_in_year}"
        )
    if terms.rate_type is RateType.PER_MONTH:
        in_month = calendar.monthrange(period_from.year, period_from.month)[1]
        fraction = rate / _HUNDRED
        return base * fraction * Decimal(days) / Decimal(in_month), (
            f"{principal} × {rate:g}% × {days} дн. / {in_month}"
        )
    raise AssertionError(f"тип ставки {terms.rate_type} не является повременным")


def calculate_penalty(
    principal: int,
    start: date,
    end: date,
    terms: PenaltyTerms,
    *,
    events: tuple[PrincipalEvent, ...] | list[PrincipalEvent] = (),
    claimed_amount: int | None = None,
    breach: str = "",
) -> PenaltyCalculation:
    """Посчитать неустойку по установленным условиям и подтверждённым данным.

    ``start`` — первый день, за который начисляется ответственность, ``end`` —
    последний, оба включительно. Определить их обязана вызывающая сторона по
    договору и закону: включается ли день наступления срока, здесь угадывать
    нечем, и молчаливое «плюс один день» стоило бы клиенту точности расчёта.

    Возвращается либо расчёт с таблицей, либо ``NEEDS_VERIFICATION`` с
    названной причиной. Исключение поднимается только на данных, которые вообще
    не являются расчётными: отрицательный долг, нулевая ставка, неверные типы.
    """
    if not isinstance(start, date) or not isinstance(end, date):
        raise ValueError("Границы периода просрочки должны быть датами")
    if principal < 0:
        raise ValueError("Сумма обязательства не может быть отрицательной")

    events = tuple(events)
    claimed = None if claimed_amount is None else int(claimed_amount)

    if not terms.has_basis:
        return _needs(
            "основание неустойки не подтверждено: не указан ни пункт договора, ни норма закона",
            terms=terms,
            claimed_amount=claimed,
        )
    if terms.legal_basis.strip() and not terms.legal_basis_source.strip():
        return _needs(
            f"норма «{terms.legal_basis.strip()}» не подтверждена официальным источником",
            terms=terms,
            claimed_amount=claimed,
        )
    if not terms.rate_source.strip():
        return _needs(
            "размер неустойки не подтверждён: не указано, откуда взята ставка",
            terms=terms,
            claimed_amount=claimed,
        )
    if breach.strip() and terms.breach.strip() and breach.strip() != terms.breach.strip():
        return _needs(
            f"условие об ответственности установлено за «{terms.breach.strip()}», "
            f"а требование заявлено за «{breach.strip()}»",
            terms=terms,
            claimed_amount=claimed,
        )

    opening = principal + sum(int(e.delta) for e in events if e.on < start)
    if opening <= 0:
        return _needs(
            "на начало периода задолженность отсутствует: неустойка не начисляется",
            terms=terms,
            claimed_amount=claimed,
        )

    if end < start:
        # Просрочка ещё не наступила либо период пуст. Это не ошибка данных и не
        # повод для маркера проверки: начислять просто не за что.
        return PenaltyCalculation(
            status=CalculationStatus.CALCULATED,
            raw_total=0,
            total=0,
            claimed_amount=claimed,
            reasons=("просрочка за указанный период не наступила",),
            terms=terms,
        )

    if terms.rate_type is RateType.FIXED:
        amount = _round_tenge(terms.rate)
        intervals = (
            PenaltyInterval(
                period_from=start,
                period_to=end,
                days=(end - start).days + 1,
                principal=opening,
                rate=terms.rate,
                rate_type=terms.rate_type,
                subtotal=amount,
                formula=f"фиксированный штраф {terms.rate:g} тенге",
            ),
        )
        return _finish(intervals, opening, terms, claimed)

    if terms.rate_type is RateType.PERCENT_OF_OBLIGATION:
        amount = _round_tenge(Decimal(opening) * terms.rate / _HUNDRED)
        intervals = (
            PenaltyInterval(
                period_from=start,
                period_to=end,
                days=(end - start).days + 1,
                principal=opening,
                rate=terms.rate,
                rate_type=terms.rate_type,
                subtotal=amount,
                formula=f"{opening} × {terms.rate:g}%",
            ),
        )
        return _finish(intervals, opening, terms, claimed)

    intervals_list: list[PenaltyInterval] = []
    for period_from, period_to, balance, ending in _balance_timeline(
        principal, start, end, events
    ):
        if balance <= 0:
            # Долг погашен: дальше начислять не на что. Это не ошибка — просто
            # ответственность за этот отрезок не возникает.
            continue
        parts = (
            _split_calendar_months(period_from, period_to)
            if terms.rate_type is RateType.PER_MONTH
            else [(period_from, period_to)]
        )
        for index, (part_from, part_to) in enumerate(parts):
            days = (part_to - part_from).days + 1
            exact, formula = _interval_amount(balance, days, part_from, part_to, terms)
            intervals_list.append(
                PenaltyInterval(
                    period_from=part_from,
                    period_to=part_to,
                    days=days,
                    principal=balance,
                    rate=terms.rate,
                    rate_type=terms.rate_type,
                    # Округление построчно, а не только в итоге: таблица попадает
                    # в документ, и видимые строки обязаны складываться в
                    # видимый итог. Иначе суд и ответчик сложат столбец и
                    # получат не ту сумму, что в просительной части.
                    subtotal=_round_tenge(exact),
                    formula=formula,
                    event_ending_period=ending if index == len(parts) - 1 else "",
                )
            )

    if not intervals_list:
        return _needs(
            "за период начислять не на что: задолженность погашена",
            terms=terms,
            claimed_amount=claimed,
        )

    return _finish(tuple(intervals_list), opening, terms, claimed)


def _finish(
    intervals: tuple[PenaltyInterval, ...],
    base_for_cap: int,
    terms: PenaltyTerms,
    claimed: int | None,
) -> PenaltyCalculation:
    raw_total = sum(interval.subtotal for interval in intervals)

    cap_amount: int | None = None
    if terms.cap_amount is not None:
        cap_amount = int(terms.cap_amount)
    elif terms.cap_percent is not None:
        cap_amount = _round_tenge(Decimal(base_for_cap) * terms.cap_percent / _HUNDRED)

    if cap_amount is not None and not terms.cap_verified:
        # Предел найден, но не подтверждён. Применить его — занизить требование
        # клиента по собственной догадке; не применить молча — заявить сумму,
        # которую договор, возможно, прямо ограничивает. Оба исхода решает юрист.
        return PenaltyCalculation(
            status=CalculationStatus.NEEDS_VERIFICATION,
            intervals=intervals,
            raw_total=raw_total,
            total=raw_total,
            cap_amount=cap_amount,
            claimed_amount=claimed,
            reasons=("предел неустойки не подтверждён договором или законом",),
            terms=terms,
        )

    total = raw_total if cap_amount is None else min(raw_total, cap_amount)
    return PenaltyCalculation(
        status=CalculationStatus.CALCULATED,
        intervals=intervals,
        raw_total=raw_total,
        total=total,
        cap_amount=cap_amount,
        capped=cap_amount is not None and raw_total > cap_amount,
        claimed_amount=claimed,
        terms=terms,
    )
