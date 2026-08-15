"""Produce QUALITY_REPORT.md from an actual run of the evaluation and acceptance suites.

The report is generated, never written by hand, so every number in it comes from the same code
paths the tests exercise. All cases are synthetic: the file contains no client data and is safe to
share or attach to a review.

    python scripts/generate_quality_report.py [--output QUALITY_REPORT.md]
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from korgan_legal_ai.blueprints.registry import blueprint_by_key  # noqa: E402
from korgan_legal_ai.evals import (  # noqa: E402
    ACCEPTANCE_CASES,
    EVAL_CASES,
    CaseResult,
    run_suite,
)
from korgan_legal_ai.house_style import load_rules, review_claim_presentation  # noqa: E402

CHECK = "✅"
CROSS = "❌"


def _mark(value: bool) -> str:
    return CHECK if value else CROSS


def _style_table(case_result: CaseResult) -> list[str]:
    """All eleven derived house-style rules, with the reason when one is not met."""
    rules = load_rules()
    findings = {
        finding.rule_id: finding
        for finding in review_claim_presentation(
            case_result.result.document, case_result.result.calculation
        )
    }
    lines = [
        "| № | Правило STYLE_GUIDE | Соответствие | Комментарий |",
        "|---|---|---|---|",
    ]
    for index, rule in enumerate(rules.rules, start=1):
        finding = findings.get(rule.id)
        if finding is None:
            status = "—"
            detail = "Правило не проверяется автоматически для этого типа документа."
        else:
            status = _mark(finding.satisfied)
            detail = finding.detail or ("Соблюдено." if finding.satisfied else "Не соблюдено.")
        lines.append(f"| {index} | {rule.title} | {status} | {detail} |")
    return lines


def _case_section(case_result: CaseResult, *, level: str = "###") -> list[str]:
    case = case_result.case
    blueprint = blueprint_by_key(case.blueprint_key)
    lines = [f"{level} {case.id} — {case.title}", ""]

    if case_result.error:
        lines += [f"{CROSS} **Кейс не выполнен:** `{case_result.error}`", ""]
        return lines

    calculation = case_result.result.calculation
    lines += [
        f"**Тип документа:** {blueprint.title.capitalize()} — {blueprint.subject}  ",
        f"**Дата расчёта:** {case.as_of.strftime('%d.%m.%Y')}",
        "",
        "**Исходные факты (ответы в диалоге):**",
        "",
        "| Вопрос | Ответ |",
        "|---|---|",
    ]
    for field_id, value in case.answers.items():
        lines.append(f"| `{field_id}` | {value} |")

    lines += [
        "",
        "**Проверка расчёта вручную:**",
        "",
        f"- Формула: {case.formula}",
        "",
        "| Позиция | Ожидание (вручную) | Калькулятор | Совпадение |",
        "|---|---|---|---|",
    ]
    for label, expected, actual in (
        ("Основной долг", case.expected_principal, calculation.principal),
        ("Неустойка", case.expected_penalty, calculation.penalty),
        ("Итого", case.expected_total, calculation.total),
    ):
        if expected is None:
            lines.append(f"| {label} | не применяется | {actual} | — |")
        else:
            lines.append(f"| {label} | {expected} | {actual} | {_mark(expected == actual)} |")

    if calculation.penalty_periods:
        lines += [
            "",
            "**Периоды начисления неустойки:**",
            "",
            "| Период | Дней | Остаток долга | Начислено |",
            "|---|---|---|---|",
        ]
        for period in calculation.penalty_periods:
            lines.append(
                f"| {period.start.strftime('%d.%m.%Y')} — {period.end.strftime('%d.%m.%Y')} "
                f"| {period.days} | {period.outstanding} | {period.amount} |"
            )

    lines += ["", "**Критерии:**", "", "| Критерий | Результат | Детали |", "|---|---|---|"]
    for criterion in case_result.criteria:
        detail = criterion.detail if not criterion.passed else ""
        lines.append(f"| `{criterion.id}` | {_mark(criterion.passed)} | {detail} |")

    document = case_result.result.document
    lines += [
        "",
        f"**Статус готовности:** `{document.readiness.value}`",
        "",
        "**Очередь NEEDS_VERIFICATION (выводится отдельно от текста):**",
        "",
    ]
    if document.needs_verification:
        from korgan_legal_ai.domain.verification import verification_label

        for item in document.needs_verification:
            lines.append(f"- `{item}` — {verification_label(item)}")
    else:
        lines.append("- пусто")

    lines += ["", "**Соответствие STYLE_GUIDE (11 пунктов):**", ""]
    lines += _style_table(case_result)
    if case.style_exempt:
        lines.append("")
        for rule_id, reason in case.style_exempt.items():
            lines.append(f"> Исключение `{rule_id}`: {reason}")

    lines += [
        "",
        "<details><summary>Сгенерированный документ</summary>",
        "",
        "```text",
        case_result.document_text.rstrip(),
        "```",
        "",
        "</details>",
        "",
    ]
    return lines


def build_report() -> str:
    eval_result = run_suite(EVAL_CASES)
    acceptance_result = run_suite(ACCEPTANCE_CASES)

    by_id = {case.case.id: case for case in acceptance_result.cases}
    trap_cases = [
        case for case in eval_result.cases if "trap" in case.case.tags
    ] + [case for case in acceptance_result.cases if "trap" in case.case.tags]

    gate1 = eval_result.passed
    gate2 = all(
        by_id[case_id].passed for case_id in ("A1_construction_penalty", "A2_appeal_against_act", "A3_setoff_partial_payments")
    )
    gate3 = all(case.passed for case in trap_cases)
    gate4 = by_id["A4_missing_data_discipline"].passed

    lines: list[str] = [
        "# KORGAN Legal AI — отчёт о качестве",
        "",
        f"Сформирован автоматически: `python scripts/generate_quality_report.py`  ",
        f"Дата генерации: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}  ",
        f"Дата расчёта в кейсах: {date(2026, 8, 15).strftime('%d.%m.%Y')}",
        "",
        "Все кейсы синтетические: стороны, суммы и документы вымышлены. Ни один пример не взят "
        "из приватного корпуса реальных исков, поэтому отчёт можно передавать и обсуждать.",
        "",
        "Прогон выполняется **без базы данных, без сети и без LLM**: используется fail-closed "
        "citation gateway. Это конфигурация, в которой выдумать норму проще всего, поэтому именно "
        "её имеет смысл измерять.",
        "",
        "## Сводка по gate",
        "",
        "| Gate | Что проверяет | Результат |",
        "|---|---|---|",
        f"| 1 | Регрессия eval suite: {eval_result.passed_criteria}/{eval_result.total_criteria} "
        f"критериев по {len(eval_result.cases)} кейсам | {_mark(gate1)} |",
        f"| 2 | Новые кейсы вне eval suite (денежный с неустойкой, без расчёта, с частичными "
        f"оплатами) | {_mark(gate2)} |",
        f"| 3 | Кейсы-ловушки на задвоение и числовые баги ({len(trap_cases)} шт.) | {_mark(gate3)} |",
        f"| 4 | Дисциплина NEEDS_VERIFICATION на неполных данных | {_mark(gate4)} |",
        "| 5 | Пакет собран, юридическая корректность человеком не подтверждена | "
        f"{CHECK} собран |",
        "",
    ]

    failures = eval_result.failures() + acceptance_result.failures()
    if failures:
        lines += ["### Непройденные критерии", "", "| Кейс | Критерий | Детали |", "|---|---|---|"]
        for case_id, criterion in failures:
            lines.append(f"| {case_id} | `{criterion.id}` | {criterion.detail} |")
        lines.append("")
    else:
        lines += ["Непройденных критериев нет.", ""]

    lines += [
        "## Gate 1 — регрессия eval suite",
        "",
        f"Кейсов: **{len(eval_result.cases)}**, критериев: **{eval_result.total_criteria}**, "
        f"пройдено: **{eval_result.passed_criteria}**.",
        "",
        "Шесть критериев на каждый кейс:",
        "",
        "1. `calc.matches_manual_derivation` — расчёт совпадает с формулой, выведенной вручную;",
        "2. `calc.no_double_counting` — сумма договора не становится вторым требованием;",
        "3. `doc.amounts_match_calculation` — все суммы в тексте взяты из калькулятора;",
        "4. `law.no_unverified_citations` — ни одной статьи без подтверждённого источника;",
        "5. `verification.discipline` — NEEDS_VERIFICATION только на реально открытых вопросах;",
        "6. `style.house_layout` — разметка соответствует применимым правилам стиля.",
        "",
        "| Кейс | Название | Критериев пройдено |",
        "|---|---|---|",
    ]
    for case in eval_result.cases:
        passed = sum(1 for item in case.criteria if item.passed)
        lines.append(
            f"| `{case.case.id}` | {case.case.title} | {passed}/{len(case.criteria)} "
            f"{_mark(case.passed)} |"
        )
    lines.append("")

    lines += ["## Gate 2 — новые кейсы вне eval suite", ""]
    for case_id in (
        "A1_construction_penalty",
        "A2_appeal_against_act",
        "A3_setoff_partial_payments",
    ):
        lines += _case_section(by_id[case_id])

    lines += [
        "## Gate 3 — кейсы-ловушки на задвоение и числовые баги",
        "",
        "| Ловушка | Кейс | Результат |",
        "|---|---|---|",
    ]
    trap_labels = {
        "E2_multiple_payments": "несколько частичных оплат, неустойка по убывающему остатку",
        "E3_repaid_penalty_only": "долг погашен полностью, неустойка за период до погашения",
        "E4_other_amount_echo": "«иные суммы» дублируют уже учтённый долг",
        "E1_partial_payment": "частичная оплата: долг = договор − оплата",
    }
    for case in trap_cases:
        label = trap_labels.get(case.case.id, case.case.title)
        lines.append(f"| {label} | `{case.case.id}` | {_mark(case.passed)} |")
    lines.append("")
    for case in trap_cases:
        lines += _case_section(case)

    lines += ["## Gate 4 — дисциплина NEEDS_VERIFICATION", ""]
    lines += _case_section(by_id["A4_missing_data_discipline"])

    lines += [
        "## Gate 5 — что остаётся человеку",
        "",
        "Автоматика в этом отчёте проверила **внутреннюю согласованность**: совпадение сумм с "
        "независимо выведенной формулой, отсутствие задвоения, отсутствие статей без "
        "подтверждённого источника, отсутствие ложных отметок на предоставленных данных и "
        "соответствие разметки фирменному стилю.",
        "",
        "Автоматика **не проверяла и не может проверить**:",
        "",
        "- правильность выбранной правовой позиции и квалификации отношений;",
        "- применимость конкретных норм к конкретным обстоятельствам;",
        "- актуальность редакций норм, ставок госпошлины и правил подсудности "
        "(в этом прогоне канонический корпус не подключён, поэтому таких ссылок в документах нет);",
        "- полноту и достоверность фактов, изложенных клиентом;",
        "- тактическую целесообразность заявленных требований.",
        "",
        "Максимальный машинный статус документа — `READY FOR FINAL HUMAN REVIEW`; в этом прогоне "
        "все документы имеют статус `LAWYER-REVIEW DRAFT`, поскольку часть вопросов осталась "
        "в очереди NEEDS_VERIFICATION.",
        "",
        "> **Требуется проверка юристом перед использованием.**",
        "",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="QUALITY_REPORT.md")
    args = parser.parse_args()

    report = build_report()
    path = REPO_ROOT / args.output
    path.write_text(report, encoding="utf-8")
    print(f"Отчёт записан: {path.relative_to(REPO_ROOT)} ({len(report)} символов)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
