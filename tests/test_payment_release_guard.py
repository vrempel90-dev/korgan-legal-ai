from korgan.payment_release_guard import PAID_DOCUMENT_KINDS, can_release_paid_document


def test_every_paid_document_stays_locked_without_strict_ai_verification() -> None:
    assert PAID_DOCUMENT_KINDS == {"claim", "pretrial", "pretrial_response", "response", "contract"}
    for kind in PAID_DOCUMENT_KINDS:
        assert not can_release_paid_document(
            kind=kind,
            receipt_submitted=False,
            receipt_precheck_passed=False,
            ai_verified=False,
        ).allowed
        assert not can_release_paid_document(
            kind=kind,
            receipt_submitted=True,
            receipt_precheck_passed=False,
            ai_verified=False,
        ).allowed
        assert not can_release_paid_document(
            kind=kind,
            receipt_submitted=True,
            receipt_precheck_passed=True,
            ai_verified=False,
        ).allowed


def test_paid_document_releases_or_generates_immediately_after_ai_verification() -> None:
    for kind in PAID_DOCUMENT_KINDS:
        decision = can_release_paid_document(
            kind=kind,
            receipt_submitted=True,
            receipt_precheck_passed=True,
            ai_verified=True,
        )
        assert decision.allowed
        assert decision.reason == "payment_ai_verified"


def test_legacy_admin_confirmation_remains_backward_compatible_only() -> None:
    decision = can_release_paid_document(
        kind="claim",
        receipt_submitted=True,
        receipt_precheck_passed=True,
        admin_confirmed=True,
    )
    assert decision.allowed
    assert decision.reason == "payment_legacy_admin_confirmed"
