"""The evaluation suite is a gate, not a report: every criterion must pass."""
from __future__ import annotations

import pytest

from korgan_legal_ai.evals import ACCEPTANCE_CASES, EVAL_CASES, run_case, run_suite


def test_suite_shape_is_eight_cases_and_forty_eight_criteria() -> None:
    result = run_suite(EVAL_CASES)

    assert len(result.cases) == 8
    assert result.total_criteria == 48


def test_every_eval_criterion_passes() -> None:
    result = run_suite(EVAL_CASES)

    failures = [
        f"{case_id}: {item.id} — {item.detail}" for case_id, item in result.failures()
    ]
    errors = [f"{case.case.id}: {case.error}" for case in result.cases if case.error]
    assert not errors, "\n".join(errors)
    assert not failures, "\n".join(failures)
    assert result.passed_criteria == result.total_criteria


def test_every_acceptance_criterion_passes() -> None:
    result = run_suite(ACCEPTANCE_CASES)

    failures = [
        f"{case_id}: {item.id} — {item.detail}" for case_id, item in result.failures()
    ]
    errors = [f"{case.case.id}: {case.error}" for case in result.cases if case.error]
    assert not errors, "\n".join(errors)
    assert not failures, "\n".join(failures)


@pytest.mark.parametrize("case", EVAL_CASES + ACCEPTANCE_CASES, ids=lambda case: case.id)
def test_case_never_cites_law_the_corpus_did_not_confirm(case) -> None:
    """With no corpus connected, a document that names an article has invented it."""
    result = run_case(case)

    assert not result.error, result.error
    citation_criterion = next(
        item for item in result.criteria if item.id == "law.no_unverified_citations"
    )
    assert citation_criterion.passed, citation_criterion.detail


@pytest.mark.parametrize(
    "case",
    [case for case in EVAL_CASES + ACCEPTANCE_CASES if "trap" in case.tags],
    ids=lambda case: case.id,
)
def test_numeric_trap_cases_do_not_double_count(case) -> None:
    result = run_case(case)

    assert not result.error, result.error
    for criterion_id in ("calc.matches_manual_derivation", "calc.no_double_counting"):
        criterion = next(item for item in result.criteria if item.id == criterion_id)
        assert criterion.passed, f"{case.id}/{criterion_id}: {criterion.detail}"
