from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from korgan_legal_ai.blueprints.models import DocumentBlueprint, SectionKind
from korgan_legal_ai.blueprints.registry import CLAIM_DEBT_RECOVERY, blueprint_by_key
from korgan_legal_ai.domain.models import VerificationStatus, WorkflowResult
from korgan_legal_ai.drafting.debt_claim import DebtClaimDrafter
from korgan_legal_ai.drafting.generic import DocumentDrafter
from korgan_legal_ai.evals.cases import EvalCase
from korgan_legal_ai.house_style import review_claim_presentation
from korgan_legal_ai.interview import InterviewState, build_locked_case, build_routing, parse_answer
from korgan_legal_ai.orchestration.debt_claim import DebtClaimWorkflow
from korgan_legal_ai.orchestration.document import DocumentWorkflow
from korgan_legal_ai.procedural.checker import ProceduralChecker
from korgan_legal_ai.qa.policies import ARTICLE_RE, _citation_locator, _locator
from korgan_legal_ai.research.gateway import CitationGateway

# House-style rules that describe layout the drafter fully controls. Rules that require quoting a
# specific norm are excluded here: with no canonical corpus connected they cannot be satisfied
# without inventing law, and the suite must not reward that.
_LAYOUT_RULES_BY_SECTION = {
    SectionKind.CLAIM_PRICE: ("header.court_then_parties_then_price",),
    SectionKind.TITLE: ("heading.isk_with_subject",),
    SectionKind.CALCULATION: ("calc.explicit_formula",),
    SectionKind.PRETRIAL: ("pretrial.factual_block",),
    SectionKind.CLOSING_FORMULA: ("closing.rukovodstvuyas_proshu_sud",),
    SectionKind.ATTACHMENTS: ("attachments.numbered_from_text",),
    SectionKind.SIGNATURE: ("signature.representative_ecp",),
}
_ALWAYS_RULES = ("calc.no_empty_catch_all_row",)


@dataclass(frozen=True)
class CriterionResult:
    id: str
    description: str
    passed: bool
    detail: str = ""


@dataclass(frozen=True)
class CaseResult:
    case: EvalCase
    criteria: tuple[CriterionResult, ...]
    document_text: str
    result: WorkflowResult | None
    error: str = ""

    @property
    def passed(self) -> bool:
        return not self.error and all(item.passed for item in self.criteria)


@dataclass(frozen=True)
class SuiteResult:
    cases: tuple[CaseResult, ...]

    @property
    def total_criteria(self) -> int:
        return sum(len(case.criteria) for case in self.cases)

    @property
    def passed_criteria(self) -> int:
        return sum(1 for case in self.cases for item in case.criteria if item.passed)

    @property
    def passed(self) -> bool:
        return all(case.passed for case in self.cases)

    def failures(self) -> list[tuple[str, CriterionResult]]:
        return [
            (case.case.id, item)
            for case in self.cases
            for item in case.criteria
            if not item.passed
        ]


def build_offline_workflow(blueprint: DocumentBlueprint, as_of: date) -> DocumentWorkflow:
    """Workflow with no database, no network and no model.

    The citation gateway is the fail-closed one, so every legal reference the document could make
    is unavailable. That is deliberate: it is the configuration in which invented law would be
    easiest and therefore the one worth testing.
    """
    checker = ProceduralChecker(CitationGateway())
    if blueprint.key == CLAIM_DEBT_RECOVERY.key:
        return DebtClaimWorkflow(
            procedural=checker,
            drafter=DebtClaimDrafter(),
            as_of_date_provider=lambda: as_of,
        )
    return DocumentWorkflow(
        blueprint=blueprint,
        procedural=checker,
        drafter=DocumentDrafter(blueprint),
        as_of_date_provider=lambda: as_of,
    )


def collect_answers(case: EvalCase) -> InterviewState:
    """Replay the case through the guided dialogue exactly as a user would answer it."""
    blueprint = blueprint_by_key(case.blueprint_key)
    state = InterviewState(blueprint_key=blueprint.key)
    while True:
        field = state.next_field()
        if field is None:
            return state
        raw = case.answers.get(field.id)
        if raw is None:
            raw = "не знаю" if field.unknown_ok else ""
        parsed = parse_answer(field, raw)
        if not parsed.ok:
            raise ValueError(f"{case.id}: ответ на «{field.id}» не принят — {parsed.error}")
        state.record(field.id, parsed.value)


def _criterion_calculation(case: EvalCase, result: WorkflowResult) -> CriterionResult:
    calculation = result.calculation
    expectations = (
        ("основной долг", case.expected_principal, calculation.principal),
        ("неустойка", case.expected_penalty, calculation.penalty),
        ("итого", case.expected_total, calculation.total),
    )
    mismatches = [
        f"{label}: ожидалось {expected}, получено {actual}"
        for label, expected, actual in expectations
        if expected is not None and expected != actual
    ]
    return CriterionResult(
        id="calc.matches_manual_derivation",
        description="Расчёт совпадает с формулой, выведенной вручную",
        passed=not mismatches,
        detail="; ".join(mismatches) or case.formula,
    )


def _criterion_no_double_counting(result: WorkflowResult) -> CriterionResult:
    calculation = result.calculation
    parts = calculation.principal + calculation.penalty + calculation.interest + calculation.other
    problems: list[str] = []
    if parts != calculation.total:
        problems.append(f"итог {calculation.total} не равен сумме позиций {parts}")
    if calculation.contract_amount is not None:
        # The contract sum is an input to the balance. If it also survives as a claimable position,
        # the same obligation is being claimed twice.
        without_payments = calculation.contract_amount - calculation.payments_total
        if calculation.payments_total > 0 and calculation.principal != max(
            without_payments, without_payments * 0
        ):
            problems.append("основной долг не равен «стоимость по договору − оплачено»")
        if calculation.total >= calculation.contract_amount + calculation.principal > 0:
            problems.append("итог включает и стоимость договора, и остаток долга")
    return CriterionResult(
        id="calc.no_double_counting",
        description="Сумма договора не превращается во второе требование поверх остатка",
        passed=not problems,
        detail="; ".join(problems),
    )


def _criterion_document_amounts(
    case: EvalCase, blueprint: DocumentBlueprint, result: WorkflowResult, text: str
) -> CriterionResult:
    if not blueprint.monetary:
        leaked = [marker for marker in ("ЦЕНА ИСКА", "Итого:") if marker in text]
        return CriterionResult(
            id="doc.amounts_match_calculation",
            description="Неденежный документ не содержит цены иска и расчёта",
            passed=not leaked,
            detail=", ".join(leaked),
        )

    total = f"{result.calculation.total}"
    problems: list[str] = []
    if f"Итого: {total}" not in text:
        problems.append("итоговая строка расчёта не совпадает с калькулятором")
    prayer_heading = blueprint.heading_for(SectionKind.PRAYER)
    prayer = text.split(prayer_heading, maxsplit=1)[-1] if prayer_heading in text else ""
    if total not in prayer:
        problems.append("сумма в просительной части не совпадает с калькулятором")
    return CriterionResult(
        id="doc.amounts_match_calculation",
        description="Все суммы в тексте взяты из детерминированного расчёта",
        passed=not problems,
        detail="; ".join(problems),
    )


def _criterion_no_unverified_law(result: WorkflowResult, text: str) -> CriterionResult:
    verified: set[tuple[str, str, str]] = set()
    for item in result.procedural.items:
        for citation in item.sources:
            if citation.status == VerificationStatus.VERIFIED and citation.article:
                parsed = _citation_locator(citation.article.strip())
                if parsed is not None:
                    verified.add(parsed)
    used = {
        _locator(match.group("article"), match.group("part"), match.group("point"))
        for match in ARTICLE_RE.finditer(text)
    }
    # Any other way of naming a statute is caught too: "ст. 148", "п. 3 ст. 149".
    used.update(
        (match.group(1), "", "") for match in re.finditer(r"\bст\.\s*(\d+)", text, re.IGNORECASE)
    )
    unverified = sorted(item for item in used if item not in verified)
    return CriterionResult(
        id="law.no_unverified_citations",
        description="Ни одной статьи без подтверждённого источника",
        passed=not unverified,
        detail=", ".join(f"статья {item[0]}" for item in unverified),
    )


def _criterion_verification_discipline(
    case: EvalCase, result: WorkflowResult, text: str
) -> CriterionResult:
    problems: list[str] = []
    # Every unresolved item must be visible in the document, not only in the machine-readable list.
    if result.document.needs_verification and "NEEDS_VERIFICATION" not in text:
        problems.append("непроверенные пункты не отмечены в тексте документа")
    for phrase in case.must_say:
        if phrase not in text:
            problems.append(f"отсутствует обязательная отметка: {phrase!r}")
    # A marker on data the user actually supplied is as damaging as an invented value.
    for phrase in case.must_not_say:
        if phrase in text:
            problems.append(f"ложная отметка на предоставленных данных: {phrase!r}")
    for item in case.expected_needs:
        if item not in result.document.needs_verification:
            problems.append(f"не отмечен действительно открытый вопрос: {item}")
    return CriterionResult(
        id="verification.discipline",
        description="NEEDS_VERIFICATION стоит только на действительно неопределённых полях",
        passed=not problems,
        detail="; ".join(problems),
    )


def _criterion_house_style(
    case: EvalCase, blueprint: DocumentBlueprint, result: WorkflowResult
) -> CriterionResult:
    expected: set[str] = set(_ALWAYS_RULES)
    for section in blueprint.sections:
        expected.update(_LAYOUT_RULES_BY_SECTION.get(section.kind, ()))
    findings = {
        finding.rule_id: finding
        for finding in review_claim_presentation(result.document, result.calculation)
    }
    unmet = sorted(
        rule_id
        for rule_id in expected
        if rule_id in findings
        and not findings[rule_id].satisfied
        and rule_id not in case.style_exempt
    )
    return CriterionResult(
        id="style.house_layout",
        description="Разметка соответствует применимым правилам фирменного стиля",
        passed=not unmet,
        detail=", ".join(unmet),
    )


def run_case(case: EvalCase) -> CaseResult:
    blueprint = blueprint_by_key(case.blueprint_key)
    try:
        state = collect_answers(case)
        missing = state.missing_required()
        if missing:
            raise ValueError(
                "диалог не собрал обязательные поля: " + ", ".join(f.id for f in missing)
            )
        locked = build_locked_case(blueprint, state.answers)
        workflow = build_offline_workflow(blueprint, case.as_of)
        result = workflow.run(locked, build_routing(blueprint))
    except Exception as exc:  # noqa: BLE001 - the report records the failure rather than raising
        return CaseResult(case=case, criteria=(), document_text="", result=None, error=f"{type(exc).__name__}: {exc}")

    text = result.document.text
    criteria = (
        _criterion_calculation(case, result),
        _criterion_no_double_counting(result),
        _criterion_document_amounts(case, blueprint, result, text),
        _criterion_no_unverified_law(result, text),
        _criterion_verification_discipline(case, result, text),
        _criterion_house_style(case, blueprint, result),
    )
    return CaseResult(case=case, criteria=criteria, document_text=text, result=result)


def run_suite(cases) -> SuiteResult:
    return SuiteResult(cases=tuple(run_case(case) for case in cases))
