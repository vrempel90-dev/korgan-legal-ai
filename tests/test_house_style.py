from __future__ import annotations

import re

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


def test_provenance_identifies_documents_without_revealing_parties() -> None:
    from korgan_legal_ai.house_style import load_provenance

    provenance = load_provenance()
    blob = repr(provenance)

    assert len(provenance.documents) == 12
    for document in provenance.documents:
        assert document.document_id.startswith("kzc-")
        assert len(document.sha256) == 64
        # Dispute type is not personal data; party names, file names and identifiers never ship.
        assert document.dispute_type.replace("_", "").isalpha()
    # Strongest available check, and one that names no real party: the shipped provenance is
    # pure ASCII identifiers, so no Cyrillic party name, address or document title can hide in it.
    assert blob.isascii()
    # No digit run outside the hex hashes, so an ИИН/БИН cannot hide in any other field.
    without_hashes = blob
    for document in provenance.documents:
        without_hashes = without_hashes.replace(document.sha256, "")
    assert not re.search(r"\d{5,}", without_hashes)


def test_every_style_rule_traces_back_to_named_documents() -> None:
    from korgan_legal_ai.house_style import load_provenance, load_rules

    rules, provenance = load_rules(), load_provenance()
    known = {document.document_id for document in provenance.documents}

    for rule in rules.rules:
        trace = provenance.for_rule(rule.id)
        assert trace is not None, f"rule {rule.id} has no provenance"
        assert trace.source_count == rule.source_count
        assert set(trace.derived_from) <= known


def test_withdrawing_a_document_rebuilds_the_derived_rules() -> None:
    from korgan_legal_ai.house_style import load_provenance

    provenance = load_provenance()
    victim = "kzc-09"
    rebuilt = provenance.without_document(victim)

    assert provenance.document(victim) is not None
    assert rebuilt.document(victim) is None
    assert len(rebuilt.documents) == len(provenance.documents) - 1
    for item in rebuilt.provenance:
        assert victim not in item.derived_from
        # A rule that lost its only source does not survive unattributed.
        assert item.source_count > 0


def test_withdrawing_the_sole_source_removes_the_rule_entirely() -> None:
    from korgan_legal_ai.house_style.provenance import (
        CorpusDocument,
        CorpusProvenance,
        RuleProvenance,
    )

    corpus = CorpusProvenance(
        corpus_version=1,
        documents=(
            CorpusDocument("kzc-aa", "supply", "a" * 64, 1),
            CorpusDocument("kzc-bb", "lease", "b" * 64, 1),
        ),
        provenance=(
            RuleProvenance("rule.shared", ("kzc-aa", "kzc-bb")),
            RuleProvenance("rule.only_aa", ("kzc-aa",)),
        ),
    )

    rebuilt = corpus.without_document("kzc-aa")

    assert corpus.orphaned_rules(rebuilt) == ("rule.only_aa",)
    assert rebuilt.for_rule("rule.only_aa") is None
    assert rebuilt.for_rule("rule.shared").derived_from == ("kzc-bb",)
