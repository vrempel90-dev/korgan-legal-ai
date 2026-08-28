from korgan.payment_release_guard import PAID_DOCUMENT_KINDS, can_release_paid_document


def test_every_paid_document_stays_locked_without_receipt_and_admin_confirmation() -> None:
    assert PAID_DOCUMENT_KINDS == {"claim", "pretrial", "pretrial_response", "response", "contract"}
    for kind in PAID_DOCUMENT_KINDS:
        assert not can_release_paid_document(
            kind=kind,
            receipt_submitted=False,
            receipt_precheck_passed=False,
            admin_confirmed=False,
        ).allowed
        assert not can_release_paid_document(
            kind=kind,
            receipt_submitted=True,
            receipt_precheck_passed=False,
            admin_confirmed=False,
        ).allowed
        assert not can_release_paid_document(
            kind=kind,
            receipt_submitted=True,
            receipt_precheck_passed=True,
            admin_confirmed=False,
        ).allowed


def test_paid_document_releases_or_generates_only_after_all_payment_checks() -> None:
    for kind in PAID_DOCUMENT_KINDS:
        decision = can_release_paid_document(
            kind=kind,
            receipt_submitted=True,
            receipt_precheck_passed=True,
            admin_confirmed=True,
        )
        assert decision.allowed
        # Причина выпуска стала различать способ подтверждения оплаты:
        # детерминированная проверка Kaspi ОФД — основной путь, проверка ИИ и
        # подтверждение администратором остались только для транзакций,
        # открытых до появления ОФД-верификатора. Здесь сценарий именно
        # легаси-подтверждения, поэтому и причина соответствующая.
        assert decision.reason == "payment_legacy_admin_confirmed"

        ofd = can_release_paid_document(
            kind=kind,
            receipt_submitted=True,
            receipt_precheck_passed=True,
            ofd_verified=True,
        )
        assert ofd.allowed
        assert ofd.reason == "payment_kaspi_ofd_verified", "основной путь — фискальный чек Kaspi"
