from __future__ import annotations

import inspect

import korgan.payment_release_guard as payment_release_guard
import korgan.prepayment_gate as prepayment_gate
import korgan.prepayment_runtime as prepayment_runtime
import korgan.request_scope as request_scope
import korgan.strict_bot as strict_bot


def test_all_five_document_generators_are_wrapped_by_prepayment_gate() -> None:
    source = inspect.getsource(prepayment_gate.install_generation_prepayment_gate)
    expected = {
        "claim": "universal_claim_runtime._generate_now = claim_guarded",
        "pretrial": "pretrial_runtime._generate = pretrial_guarded",
        "pretrial_response": "pretrial_response_runtime._generate = pretrial_response_guarded",
        "response": "universal_document_runtime._send_response = response_guarded",
        "contract": "universal_document_runtime._send_contract = contract_guarded",
    }
    for kind, statement in expected.items():
        assert statement in source, kind
        assert f'kind="{kind}"' in source, kind


def test_production_runtime_does_not_install_old_post_generation_payment_gate() -> None:
    source = inspect.getsource(strict_bot)
    assert "from korgan.payment_gate import install_payment_gate" not in source
    assert "install_payment_gate()" not in source
    assert "install_generation_prepayment_gate()" in source
    assert "dp.include_router(prepayment_router)" in source
    assert source.index("dp.include_router(prepayment_router)") < source.index("dp.include_router(payment_router)")


def test_prepayment_copy_never_claims_document_is_already_ready() -> None:
    ru = prepayment_gate.prepayment_offer_text("claim", "ru", 1000)
    kk = prepayment_gate.prepayment_offer_text("claim", "kk", 1000)
    assert "Документ готов" not in ru
    assert "AI ещё не формировал документ" in ru
    assert "только после подтверждения оплаты" in ru
    assert "AI құжатты әлі дайындаған жоқ" in kk


def test_prepayment_admin_callbacks_use_negative_transaction_ids_only() -> None:
    negative = prepayment_runtime._parse_admin_callback("pay:ok:123:-456:claim:ru:abcdef123456")
    positive = prepayment_runtime._parse_admin_callback("pay:ok:123:456:claim:ru:abcdef123456")
    assert negative == ("ok", 123, -456, "claim", "ru", "abcdef123456")
    assert positive is None


def test_paid_generation_callback_is_separate_and_signed() -> None:
    assert prepayment_runtime._parse_generation_callback(
        "pay:generate:-456:pretrial_response:ru:abcdef123456"
    ) == (-456, "pretrial_response", "ru", "abcdef123456")
    assert prepayment_runtime._parse_generation_callback(
        "pay:generate:456:claim:ru:abcdef123456"
    ) is None


def test_new_request_clears_all_payment_authorization_fields() -> None:
    keys = request_scope._REQUEST_SCOPED_KEYS
    required = {
        "payment_admin_doc_message_id",
        "payment_kind",
        "payment_language",
        "payment_signature",
        "prepayment_transaction_id",
        "prepayment_request_id",
        "prepayment_kind",
        "prepayment_language",
        "prepayment_confirmed_request_id",
        "prepayment_confirmed_kind",
        "prepayment_confirmed_transaction_id",
        "prepayment_generation_started_request_id",
        "prepayment_consumed_request_id",
    }
    assert required <= keys


def test_payment_confirmation_guard_covers_every_menu_document() -> None:
    assert payment_release_guard.PAID_DOCUMENT_KINDS == frozenset(
        {"claim", "pretrial", "pretrial_response", "response", "contract"}
    )
    for kind in payment_release_guard.PAID_DOCUMENT_KINDS:
        blocked = payment_release_guard.can_release_paid_document(
            kind=kind,
            receipt_submitted=True,
            receipt_precheck_passed=True,
            admin_confirmed=False,
        )
        allowed = payment_release_guard.can_release_paid_document(
            kind=kind,
            receipt_submitted=True,
            receipt_precheck_passed=True,
            admin_confirmed=True,
        )
        assert blocked.allowed is False, kind
        assert allowed.allowed is True, kind
