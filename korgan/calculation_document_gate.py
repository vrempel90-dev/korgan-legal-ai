"""Сверка расчёта с текстом документа перед выдачей клиенту.

Расчёт может быть верным, а документ — всё равно негодным: сумма из таблицы
расходится с суммой в мотивировочной части, а в просительной стоит третья.
Так выглядит документ, который переписывали по частям, и именно это первым
замечает суд.

Модуль ничего не считает и ничего не исправляет. Он сравнивает то, что вернул
``penalty_engine``, с тем, что фактически написано в документе, и при любом
расхождении закрывает выдачу. Молча подставить «правильное» число нельзя: если
цифры разошлись, неизвестно, какая часть документа устарела, а какая верна.
"""

from __future__ import annotations

from dataclasses import dataclass

from korgan.legal_calc import format_kzt
from korgan.penalty_engine import PenaltyCalculation


def _money(value: object) -> str:
    """Сумма в том же виде, в каком она стоит в документе.

    Причина расхождения читается человеком и сравнивается им с текстом иска.
    «12000000» и «12 000 000 тенге» — одно число, но глазом они сверяются
    по-разному, и именно в такой строке ошибиться на разряд проще всего.
    """
    try:
        return format_kzt(int(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return str(value)


@dataclass(frozen=True, slots=True)
class DocumentAmounts:
    """Суммы, фактически стоящие в тексте документа.

    Их извлекают из готового текста, а не берут из расчёта, — иначе сверка
    сравнивала бы расчёт сам с собой и пропускала ровно ту ошибку, ради которой
    она существует.
    """

    #: Основной долг в описательной части.
    principal_in_document: int
    #: Неустойка в мотивировочной части.
    penalty_in_reasoning: int
    #: Итог таблицы расчёта.
    penalty_in_calculation: int
    #: Неустойка в просительной части.
    penalty_in_relief: int
    #: Основной долг в просительной части.
    principal_in_relief: int
    #: Общая взыскиваемая сумма в просительной части.
    total_in_relief: int
    #: Прочие подтверждённые денежные требования, вошедшие в общую сумму.
    other_verified_claims: int = 0


@dataclass(frozen=True, slots=True)
class GateResult:
    ready: bool
    reasons: tuple[str, ...] = ()


def check_calculation_against_document(
    calculation: PenaltyCalculation,
    amounts: DocumentAmounts,
    *,
    principal: int,
) -> GateResult:
    """Пропустить документ к выдаче только при полном совпадении сумм.

    ``principal`` — основной долг, установленный по делу; ``calculation`` —
    результат детерминированного расчёта; ``amounts`` — числа из текста.
    """
    reasons: list[str] = []

    if not calculation.ready:
        reasons.append(
            "расчёт не завершён: " + "; ".join(calculation.reasons)
            if calculation.reasons
            else "расчёт не завершён"
        )

    if calculation.claim_matches is False:
        reasons.append(
            f"сумма, названная клиентом ({_money(calculation.claimed_amount)}), "
            f"не совпадает с расчётом ({_money(calculation.total)})"
        )

    table_total = sum(row.subtotal for row in calculation.intervals)
    if calculation.intervals and table_total != calculation.raw_total:
        reasons.append(
            f"строки таблицы расчёта дают {_money(table_total)}, "
            f"а итог до применения предела — {_money(calculation.raw_total)}"
        )

    if amounts.principal_in_document != principal:
        reasons.append(
            f"основной долг в документе ({_money(amounts.principal_in_document)}) "
            f"не совпадает с установленным ({_money(principal)})"
        )
    if amounts.principal_in_relief != principal:
        reasons.append(
            f"основной долг в просительной части ({_money(amounts.principal_in_relief)}) "
            f"не совпадает с установленным ({_money(principal)})"
        )

    penalty = calculation.total
    for where, value in (
        ("мотивировочной части", amounts.penalty_in_reasoning),
        ("таблице расчёта", amounts.penalty_in_calculation),
        ("просительной части", amounts.penalty_in_relief),
    ):
        if value != penalty:
            reasons.append(
                f"неустойка в {where} ({_money(value)}) "
                f"не совпадает с расчётом ({_money(penalty)})"
            )

    expected_total = principal + penalty + amounts.other_verified_claims
    if amounts.total_in_relief != expected_total:
        reasons.append(
            f"общая сумма в просительной части ({_money(amounts.total_in_relief)}) "
            f"не равна сумме требований ({_money(expected_total)})"
        )

    return GateResult(ready=not reasons, reasons=tuple(reasons))
