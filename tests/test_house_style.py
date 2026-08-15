from __future__ import annotations

from decimal import Decimal

from korgan_legal_ai.calculations.service import CalculationLayer
from korgan_legal_ai.domain.models import EvidenceMap, ProceduralReport
from korgan_legal_ai.drafting.debt_claim import DebtClaimDrafter
from korgan_legal_ai.house_style import load_rules, review_claim_presentation
from tests.fixtures.synthetic_claim import synthetic_partial_payment_case


def _drafted():
    case = synthetic_partial_payment_case()
    calculation = CalculationLayer().calculate_money(case.financials)
    document = DebtClaimDrafter().draft(
        case, ProceduralReport(items=[]), EvidenceMap(links=[]), calculation
    )
    return document, calculation


def test_rule_set_ships_without_any_corpus_text() -> None:
    rules = load_rules()

    assert rules.version == 1
    assert rules.ids()
    for rule in rules.rules:
        # Only identifiers and counts travel into the public repo.
        assert set(vars(rule)) == {"id", "title", "source_count", "observed_in"}
        assert rule.source_count >= 0
        # Style is never legal authority, whatever its frequency in the corpus.
        assert rule.is_legal_authority is False


def test_frequency_is_an_observation_not_an_instruction() -> None:
    rules = load_rules()
    opening = rules.get("opening.gpk8_verbatim")

    assert opening is not None
    assert opening.observed_in.endswith("/12")
    # A rule present in every corpus document still carries no authority to cite a norm.
    assert opening.is_legal_authority is False


def test_presentation_review_reports_style_without_touching_verification() -> None:
    document, calculation = _drafted()
    before = (document.readiness, tuple(document.needs_verification), document.text)

    findings = review_claim_presentation(document, calculation)

    assert findings
    # Advisory only: the document is not modified and no status is promoted.
    assert (document.readiness, tuple(document.needs_verification), document.text) == before


def test_generated_claim_follows_the_calculation_presentation_rules() -> None:
    document, calculation = _drafted()

    findings = {finding.rule_id: finding for finding in review_claim_presentation(document, calculation)}

    assert findings["calc.no_empty_catch_all_row"].satisfied is True
    assert findings["calc.debt_shown_as_derived"].satisfied is True
    assert findings["header.court_then_parties_then_price"].satisfied is True
    assert findings["calc.explicit_formula"].satisfied is True


def test_style_review_flags_an_empty_catch_all_row() -> None:
    document, calculation = _drafted()
    document.text = document.text.replace(
        "Итого:", "Иные суммы: 0 KZT\nИтого:"
    )

    findings = {finding.rule_id: finding for finding in review_claim_presentation(document, calculation)}

    assert findings["calc.no_empty_catch_all_row"].satisfied is False
    assert "задвоение" in findings["calc.no_empty_catch_all_row"].detail


def test_claim_price_stays_deterministic_under_the_style_layer() -> None:
    document, calculation = _drafted()
    review_claim_presentation(document, calculation)

    assert calculation.principal == Decimal("2400000")
    assert calculation.total == Decimal("2558400")
    assert "Иные суммы" not in document.text
