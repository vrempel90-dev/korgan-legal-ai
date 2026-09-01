"""Воспроизводимый расчёт денежных требований.

Раздел «Расчёт взыскиваемых сумм» — то место, где документ либо выдерживает
проверку юристом и судом, либо нет. Поэтому каждая позиция раскрывается целиком:

    основание · база · ставка · период · дни · формула · итог

Модуль не считает право заново. Арифметика остаётся в существующих
детерминированных калькуляторах (``legal_calc`` для статьи 353 ГК РК и
государственной пошлины, ``contractual_penalty`` для договорной неустойки);
здесь они приводятся к одной проверяемой форме.

Два правила, которые модуль обеспечивает механически:

* договорная неустойка не подменяется расчётом по статье 353 ГК РК — если
  стороны согласовали ставку, считается именно она;
* при нехватке любого элемента расчёт не выполняется. Возвращается
  ``CalculationGap`` с указанием, чего именно не хватает, и эта строка идёт в
  verification_notes. Сумма не выдумывается никогда.

Расходы на юридические услуги и судебные расходы — отдельные позиции, которые
показываются в расчёте, но не входят в цену иска: цена иска считается только по
требованиям имущественного характера.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from korgan.contractual_penalty import ContractualPenalty, ContractualPenaltyTerms, calc_contractual_penalty
from korgan.legal_calc import ARTICLE_353_LABEL, DAYS_IN_YEAR, LatePaymentPenalty, format_kzt
from korgan.penalty_engine import PenaltyCalculation


def _date(value: date) -> str:
    return value.strftime("%d.%m.%Y")


def _percent(value: Decimal) -> str:
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


@dataclass(frozen=True, slots=True)
class CalculationGap:
    """Отсутствующий элемент расчёта. Сумма остаётся неизвестной."""

    note: str
    amount: None = None


@dataclass(slots=True)
class MoneyComponent:
    """Одна позиция расчёта, раскрытая до перепроверяемых элементов."""

    title: str
    basis: str
    amount: int
    included_in_claim_price: bool = True
    penalty_base: int | None = None
    penalty_rate: str = ""
    start_date: date | None = None
    end_date: date | None = None
    days: int | None = None
    formula: str = ""
    limits: list[str] = field(default_factory=list)

    def render(self) -> str:
        """Одна строка расчёта. Детерминирована: тот же вход — тот же текст."""
        parts = [f"{self.title}: {format_kzt(self.amount)}"]
        if self.basis:
            parts.append(f"основание: {self.basis}")
        if self.penalty_base is not None:
            parts.append(f"база: {format_kzt(self.penalty_base)}")
        if self.penalty_rate:
            parts.append(f"ставка: {self.penalty_rate}")
        if self.start_date is not None and self.end_date is not None:
            parts.append(f"период: с {_date(self.start_date)} по {_date(self.end_date)}")
        if self.days is not None:
            parts.append(f"дней: {self.days}")
        for limit in self.limits:
            parts.append(limit)
        if self.formula:
            parts.append(f"расчёт: {self.formula}")
        if not self.included_in_claim_price:
            parts.append("не входит в цену иска")
        return "; ".join(parts) + "."


def principal_component(amount: int, *, basis: str) -> MoneyComponent:
    return MoneyComponent(title="Основной долг", basis=basis, amount=amount)


def contractual_penalty_component(penalty: ContractualPenalty) -> MoneyComponent:
    """Договорная неустойка по согласованной сторонами ставке."""
    clause = penalty.terms.clause
    basis = f"пункт {clause} договора" if clause else "условие договора о неустойке"
    limits: list[str] = []
    if penalty.terms.cap_percent is not None:
        limits.append(
            f"ограничение по договору: не более {_percent(penalty.terms.cap_percent)}% от суммы долга"
        )
        if penalty.capped and penalty.cap_amount is not None:
            limits.append(f"начислено до предела: {format_kzt(penalty.cap_amount)}")
    formula = (
        f"{format_kzt(penalty.principal)} × {_percent(penalty.terms.rate_percent_per_day)}% × "
        f"{penalty.days} дн. = {format_kzt(penalty.amount)}"
    )
    return MoneyComponent(
        title="Договорная неустойка",
        basis=basis,
        amount=penalty.amount,
        penalty_base=penalty.principal,
        penalty_rate=f"{_percent(penalty.terms.rate_percent_per_day)}% за каждый день просрочки",
        start_date=penalty.start,
        end_date=penalty.end,
        days=penalty.days,
        formula=formula,
        limits=limits,
    )


def late_interest_component(penalty: LatePaymentPenalty) -> MoneyComponent:
    """Неустойка по статье 353 ГК РК — только когда договорной ставки нет."""
    formula = (
        f"{format_kzt(penalty.principal)} × {penalty.rate_percent:g}% × {penalty.days} дн. / "
        f"{DAYS_IN_YEAR} = {format_kzt(penalty.amount)}"
    )
    return MoneyComponent(
        title="Неустойка за пользование чужими деньгами",
        basis=ARTICLE_353_LABEL,
        amount=penalty.amount,
        penalty_base=penalty.principal,
        penalty_rate=(
            f"базовая ставка НБ РК {penalty.rate_percent:g}% на {_date(penalty.rate_date)}"
        ),
        start_date=penalty.start,
        end_date=penalty.end,
        days=penalty.days,
        formula=formula,
    )


def interval_penalty_component(
    calculation: PenaltyCalculation, *, title: str, basis: str, rate_label: str
) -> MoneyComponent:
    """Неустойка, посчитанная по интервалам, — с раскрытой таблицей.

    Когда долг гасили частями, одной строки «база × ставка × дни» не хватает:
    база в каждом отрезке своя, и без таблицы проверяющий не может повторить
    расчёт — а расчёт, который нельзя повторить, суд не принимает. Поэтому в
    раздел выносится каждый отрезок со своим остатком, своими днями и своим
    итогом, и подытоги складываются в ту же сумму, что стоит в требовании.
    """
    rows = [
        (
            f"{_date(interval.period_from)}—{_date(interval.period_to)}: "
            f"{format_kzt(interval.principal)} × {_percent(interval.rate)}% × "
            f"{interval.days} дн. = {format_kzt(interval.subtotal)}"
            + (
                f" (остаток изменён: {interval.event_ending_period})"
                if interval.event_ending_period
                else ""
            )
        )
        for interval in calculation.intervals
    ]
    if calculation.capped and calculation.cap_amount is not None:
        rows.append(
            f"начислено {format_kzt(calculation.raw_total)}, "
            f"предъявлено в пределах ограничения {format_kzt(calculation.cap_amount)}"
        )

    first = calculation.intervals[0]
    last = calculation.intervals[-1]
    return MoneyComponent(
        title=title,
        basis=basis,
        amount=calculation.total,
        penalty_base=first.principal,
        penalty_rate=rate_label,
        start_date=first.period_from,
        end_date=last.period_to,
        days=sum(interval.days for interval in calculation.intervals),
        formula=" + ".join(format_kzt(i.subtotal) for i in calculation.intervals)
        + f" = {format_kzt(calculation.raw_total)}",
        limits=rows,
    )


def legal_services_component(amount: int, *, basis: str) -> MoneyComponent:
    return MoneyComponent(
        title="Расходы на юридические услуги",
        basis=basis,
        amount=amount,
        included_in_claim_price=False,
    )


def court_costs_component(amount: int, *, basis: str) -> MoneyComponent:
    return MoneyComponent(
        title="Судебные расходы",
        basis=basis,
        amount=amount,
        included_in_claim_price=False,
    )


def total_claim_price(components: list[MoneyComponent]) -> int:
    """Цена иска — сумма только требований имущественного характера."""
    return sum(item.amount for item in components if item.included_in_claim_price)


def render_calculation(components: list[MoneyComponent]) -> list[str]:
    """Готовые строки раздела «Расчёт взыскиваемых сумм»."""
    lines = [item.render() for item in components]
    if any(item.included_in_claim_price for item in components):
        lines.append(f"Итого цена иска: {format_kzt(total_claim_price(components))}.")
    return lines


def try_contractual_penalty_component(
    *,
    principal: int | None,
    rate_percent_per_day: Decimal | float | int | str | None,
    cap_percent: Decimal | float | int | str | None,
    clause: str,
    start: date | None,
    end: date | None,
) -> MoneyComponent | CalculationGap:
    """Посчитать договорную неустойку либо честно назвать недостающий элемент.

    Порядок проверок соответствует порядку, в котором юрист смотрит расчёт:
    сначала база, потом ставка, потом период. Первый же пробел останавливает
    расчёт — подставлять «разумное» значение вместо отсутствующего нельзя.
    """
    if not principal or principal <= 0:
        return CalculationGap("не установлена сумма основного долга")
    if not rate_percent_per_day or rate_percent_per_day <= 0:
        return CalculationGap("не установлена ставка договорной неустойки")
    if start is None:
        return CalculationGap("не установлена дата начала просрочки")
    if end is None:
        return CalculationGap("не установлена дата окончания периода просрочки")
    if end < start:
        return CalculationGap("дата окончания просрочки раньше её начала")

    penalty = calc_contractual_penalty(
        principal,
        ContractualPenaltyTerms(
            rate_percent_per_day=rate_percent_per_day,
            cap_percent=cap_percent,
            clause=clause,
        ),
        start,
        end,
    )
    return contractual_penalty_component(penalty)
