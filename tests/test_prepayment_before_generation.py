from __future__ import annotations

import asyncio
import inspect
from pathlib import Path
from types import SimpleNamespace

import korgan.payment_release_guard as payment_release_guard
import korgan.payment_runtime as payment_runtime
import korgan.prepayment_gate as prepayment_gate
import korgan.prepayment_runtime as prepayment_runtime
import korgan.request_scope as request_scope
from korgan import pretrial_response_runtime, pretrial_runtime, universal_claim_runtime, universal_document_runtime


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


def test_production_runtime_installs_prepayment_before_generators_and_keeps_fallback_gate() -> None:
    source = Path("korgan/strict_bot.py").read_text(encoding="utf-8")
    assert "from korgan.payment_gate import install_payment_gate" in source
    assert "install_payment_gate()" in source
    assert "install_generation_prepayment_gate()" in source
    assert source.index("install_payment_gate()") < source.index("install_generation_prepayment_gate()")
    assert "dp.include_router(prepayment_router)" in source
    assert source.index("dp.include_router(prepayment_router)") < source.index("dp.include_router(payment_router)")
    assert "manual payment confirmation=False" in source


def test_prepayment_copy_never_claims_document_is_already_ready() -> None:
    ru = prepayment_gate.prepayment_offer_text("claim", "ru", 1000)
    kk = prepayment_gate.prepayment_offer_text("claim", "kk", 1000)
    assert "Документ готов" not in ru
    assert "AI ещё не формировал документ" in ru
    assert "автоматически проверит чек" in ru
    assert "подтверждение администратора не требуется" in ru
    assert "AI құжатты әлі дайындаған жоқ" in kk


def test_reservation_explicitly_says_generation_has_not_started_and_ai_verifies() -> None:
    text = prepayment_gate._reservation_text(123, "request-1", "claim", "ru", 1000)
    assert "Документ ещё НЕ генерировался" in text
    assert "AI-проверка" in text


def test_paid_delivery_context_is_exactly_scoped_to_user_and_kind() -> None:
    assert not prepayment_gate.is_paid_delivery_authorized(123, "claim")
    token = prepayment_gate.begin_paid_delivery(123, "claim")
    try:
        assert prepayment_gate.is_paid_delivery_authorized(123, "claim")
        assert not prepayment_gate.is_paid_delivery_authorized(123, "contract")
        assert not prepayment_gate.is_paid_delivery_authorized(124, "claim")
    finally:
        prepayment_gate.end_paid_delivery(token)
    assert not prepayment_gate.is_paid_delivery_authorized(123, "claim")


def test_legacy_prepayment_admin_callbacks_use_negative_transaction_ids_only() -> None:
    negative = prepayment_runtime._parse_admin_callback("pay:ok:123:-456:claim:ru:abcdef123456")
    positive = prepayment_runtime._parse_admin_callback("pay:ok:123:456:claim:ru:abcdef123456")
    assert negative == ("ok", 123, -456, "claim", "ru", "abcdef123456")
    assert positive is None


def test_legacy_paid_generation_callback_remains_signed_for_old_cards() -> None:
    assert prepayment_runtime._parse_generation_callback(
        "pay:generate:-456:pretrial_response:ru:abcdef123456"
    ) == (-456, "pretrial_response", "ru", "abcdef123456")
    assert prepayment_runtime._parse_generation_callback(
        "pay:generate:456:claim:ru:abcdef123456"
    ) is None


def test_new_receipt_flow_calls_immediate_ai_verified_prepayment_generation() -> None:
    receipt_source = inspect.getsource(payment_runtime.payment_receipt_received)
    generation_source = inspect.getsource(prepayment_runtime.run_ai_verified_prepayment_generation)
    assert "if transaction_id < 0" in receipt_source
    assert "run_ai_verified_prepayment_generation" in receipt_source
    assert "ai_verified=True" in generation_source
    assert "begin_paid_delivery" in generation_source
    assert "_run_paid_generation" in generation_source
    assert "PREPAY_AI_VERIFIED_GENERATION_COMPLETED" in generation_source


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


def test_payment_confirmation_guard_covers_every_menu_document_with_ai_verification() -> None:
    assert payment_release_guard.PAID_DOCUMENT_KINDS == frozenset(
        {"claim", "pretrial", "pretrial_response", "response", "contract"}
    )
    for kind in payment_release_guard.PAID_DOCUMENT_KINDS:
        blocked = payment_release_guard.can_release_paid_document(
            kind=kind,
            receipt_submitted=True,
            receipt_precheck_passed=True,
            ai_verified=False,
        )
        allowed = payment_release_guard.can_release_paid_document(
            kind=kind,
            receipt_submitted=True,
            receipt_precheck_passed=True,
            ai_verified=True,
        )
        assert blocked.allowed is False, kind
        assert allowed.allowed is True, kind


def test_consumed_prepayment_blocks_all_five_guarded_generators(monkeypatch) -> None:
    class State:
        def __init__(self, kind: str) -> None:
            self.kind = kind

        async def get_data(self) -> dict[str, object]:
            return {
                "request_id": f"request-{self.kind}",
                "request_kind": self.kind,
                "language": "ru",
                "prepayment_confirmed_request_id": f"request-{self.kind}",
                "prepayment_confirmed_kind": self.kind,
                "prepayment_consumed_request_id": f"request-{self.kind}",
            }

    class Message:
        def __init__(self) -> None:
            self.answers: list[str] = []
            self.chat = SimpleNamespace(id=123)
            self.text = "достаточно подробные материалы для подготовки документа"

        async def answer(self, text: str, **_kwargs: object) -> None:
            self.answers.append(text)

    called: list[str] = []

    async def original_claim(_message, _state) -> None:
        called.append("claim")

    async def original_pretrial(_message, _state) -> None:
        called.append("pretrial")

    async def original_pretrial_response(_message, _state) -> None:
        called.append("pretrial_response")

    async def original_response(_message, _state) -> None:
        called.append("response")

    async def original_contract(_message, _state) -> None:
        called.append("contract")

    async def context(_state) -> str:
        return "Факты дела и доказательства. " * 10

    async def no_save(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(prepayment_gate, "_INSTALLED", False)
    monkeypatch.setattr(prepayment_gate, "_context", context)
    monkeypatch.setattr(prepayment_gate, "get_settings", lambda: SimpleNamespace(payments_enabled=True))
    monkeypatch.setattr(universal_claim_runtime, "_generate_now", original_claim)
    monkeypatch.setattr(pretrial_runtime, "_generate", original_pretrial)
    monkeypatch.setattr(pretrial_response_runtime, "_generate", original_pretrial_response)
    monkeypatch.setattr(universal_document_runtime, "_send_response", original_response)
    monkeypatch.setattr(universal_document_runtime, "_send_contract", original_contract)
    monkeypatch.setattr(pretrial_runtime, "_save_text", no_save)
    monkeypatch.setattr(pretrial_response_runtime, "_save_text", no_save)
    monkeypatch.setattr(pretrial_response_runtime, "_looks_like_pretrial_materials", lambda _text: True)
    monkeypatch.setattr(universal_document_runtime, "_save_user_text", no_save)
    monkeypatch.setattr(universal_document_runtime, "_looks_like_claim_materials", lambda _text: True)

    prepayment_gate.install_generation_prepayment_gate()
    guarded = {
        "claim": universal_claim_runtime._generate_now,
        "pretrial": pretrial_runtime._generate,
        "pretrial_response": pretrial_response_runtime._generate,
        "response": universal_document_runtime._send_response,
        "contract": universal_document_runtime._send_contract,
    }

    for kind, entrypoint in guarded.items():
        message = Message()
        asyncio.run(entrypoint(message, State(kind)))
        assert message.answers, kind
        assert "уже запускался" in message.answers[-1], kind

    assert called == []
