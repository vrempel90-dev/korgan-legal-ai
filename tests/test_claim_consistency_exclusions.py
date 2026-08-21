from __future__ import annotations

from korgan.claim_consistency_guard import claim_consistency_errors
from korgan.legal_types import ClaimDraft, VerificationStatus


def _draft() -> ClaimDraft:
    """Build a prayer containing only the principal demand."""
    return ClaimDraft(
        status=VerificationStatus.NEEDS_VERIFICATION,
        title="Исковое заявление",
        court="",
        claimant=["Истец"],
        defendant=["Ответчик"],
        price_of_claim="1 200 000 тенге",
        facts=[],
        legal_basis=[],
        requests=["Взыскать с Ответчика 1 200 000 тенге."],
        attachments=[],
        verification_notes=[],
        source_urls=[],
    )


def test_without_penalty_does_not_create_penalty_requirement() -> None:
    errors = claim_consistency_errors(
        "Прошу взыскать основную сумму 1 200 000 тенге без неустойки.",
        _draft(),
    )
    assert not any("неустойку/пеню" in error and "исчезло" in error for error in errors)


def test_mixed_positive_and_excluded_remedies_are_separated() -> None:
    errors = claim_consistency_errors(
        "Прошу взыскать основную сумму без неустойки, но взыскать судебные расходы.",
        _draft(),
    )
    assert not any("неустойку/пеню" in error and "исчезло" in error for error in errors)
    assert any("судебные расходы" in error and "нет в разделе" in error for error in errors)


def test_new_intent_verb_resets_previous_exclusion_without_comma() -> None:
    errors = claim_consistency_errors(
        "Прошу взыскать основную сумму без неустойки и взыскать судебные расходы.",
        _draft(),
    )
    assert not any("неустойку/пеню" in error and "исчезло" in error for error in errors)
    assert any("судебные расходы" in error and "нет в разделе" in error for error in errors)


def test_without_penalty_and_costs_excludes_both() -> None:
    errors = claim_consistency_errors(
        "Прошу взыскать только основную сумму без неустойки и судебных расходов.",
        _draft(),
    )
    assert not any("неустойку/пеню" in error and "исчезло" in error for error in errors)
    assert not any("судебные расходы" in error and "нет в разделе" in error for error in errors)
