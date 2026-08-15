"""Synthetic evaluation suite.

Every case is invented. Nothing here is derived from the private reference corpus, so a report can
be shared, printed in CI output or attached to a review without exposing a real client matter.

The suite runs with no database, no network and no model: the citation gateway is the fail-closed
one, which is the configuration where inventing law would be easiest and so the one worth measuring.
"""

from korgan_legal_ai.evals.cases import ACCEPTANCE_CASES, ALL_CASES, EVAL_CASES, EvalCase
from korgan_legal_ai.evals.runner import (
    CaseResult,
    CriterionResult,
    SuiteResult,
    run_case,
    run_suite,
)

__all__ = [
    "ACCEPTANCE_CASES",
    "ALL_CASES",
    "EVAL_CASES",
    "CaseResult",
    "CriterionResult",
    "EvalCase",
    "SuiteResult",
    "run_case",
    "run_suite",
]
