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
from korgan.config import Settings
from korgan.payment import ReceiptCheck, sign_user_payment


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
    # Production release semantics are behavioral: AI verification can release
    # without admin confirmation, while a non-verified receipt remains blocked.
    for kind in payment_release_guard.PAID_DOCUMENT_KINDS:
        assert payment_release_guard.can_release_paid_document(
            kind=kind,
            receipt_submitted=True,
            receipt_precheck_passed=True,
            ai_verified=True,
            admin_confirmed=False,
        ).allowed


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


def test_new_receipt_flow_routes_exact_active_request_for_all_five_kinds(monkeypatch) -> None:
    settings = Settings(
        telegram_bot_token="123456:TEST_TOKEN",
        openai_api_key="test-openai",
        payments_enabled=True,
        kaspi_payment_url="https://pay.kaspi.kz/pay/hk3wdvjz",
        kaspi_payment_recipient="OpenCourt (KORGAN)",
        document_price_kzt=1000,
    )
    calls: list[tuple[int, str, str, int]] = []

    class State:
        def __init__(self, data: dict[str, object]) -> None:
            self.data = dict(data)

        async def get_data(self) -> dict[str, object]:
            return dict(self.data)

        async def update_data(self, **kwargs: object) -> None:
            self.data.update(kwargs)

    class Message:
        def __init__(self, user_id: int) -> None:
            self.from_user = SimpleNamespace(id=user_id)
            self.answers: list[str] = []

        async def answer(self, text: str, **_kwargs: object) -> None:
            self.answers.append(text)

    async def fetch_receipt(_url: str):
        return SimpleNamespace(
            receipt_fingerprint="fiscal-hash",
            transaction_id="RNM:RRN:FP",
            amount_kzt=1000,
            seller_bin="",
            rnm="123456789012",
            fp="456789",
        )

    def issues(_receipt, expected_amount: int, **_kwargs) -> list[str]:
        assert expected_amount == 1000
        return []

    async def reserve(**_kwargs) -> bool:
        return True

    async def generate(*, message, state, user_id, transaction_id, kind, language) -> bool:
        calls.append((user_id, kind, str((await state.get_data())["request_id"]), transaction_id))
        return True

    monkeypatch.setattr(payment_runtime, "get_settings", lambda: settings)
    monkeypatch.setattr(payment_runtime, "fetch_kaspi_ofd_receipt", fetch_receipt)
    monkeypatch.setattr(payment_runtime, "fiscal_receipt_issues", issues)
    monkeypatch.setattr(payment_runtime, "reserve_verified_document_receipt", reserve)
    monkeypatch.setattr(prepayment_runtime, "run_ai_verified_prepayment_generation", generate)

    kinds = ["claim", "pretrial", "pretrial_response", "response", "contract"]
    for index, kind in enumerate(kinds, start=1):
        user_id = 1000 + index
        transaction_id = -(5000 + index)
        request_id = f"request-{kind}"
        signature = sign_user_payment(settings, user_id, transaction_id, kind, "ru")
        state = State({
            "mode": "payment_receipt",
            "request_id": request_id,
            "request_kind": kind,
            "prepayment_request_id": request_id,
            "prepayment_kind": kind,
            "prepayment_transaction_id": transaction_id,
            "payment_admin_doc_message_id": transaction_id,
            "payment_kind": kind,
            "payment_language": "ru",
            "payment_signature": signature,
            "payment_offer_time": "2026-08-18T10:00:00+05:00",
        })
        asyncio.run(payment_runtime._verify_and_release_fiscal_url(
            Message(user_id),
            state,
            "https://receipt.kaspi.kz/web/fiscal?f=123456789012&i=456789&s=1000&t=20260818110000",
        ))

    assert calls == [
        (1001, "claim", "request-claim", -5001),
        (1002, "pretrial", "request-pretrial", -5002),
        (1003, "pretrial_response", "request-pretrial_response", -5003),
        (1004, "response", "request-response", -5004),
        (1005, "contract", "request-contract", -5005),
    ]


def test_replay_storage_failure_keeps_document_blocked_and_says_do_not_repay(monkeypatch) -> None:
    settings = Settings(
        telegram_bot_token="123456:TEST_TOKEN",
        openai_api_key="test-openai",
        payments_enabled=True,
        kaspi_payment_recipient="OpenCourt (KORGAN)",
        document_price_kzt=1000,
    )
    user_id = 123
    transaction_id = -456
    kind = "claim"

    class State:
        data = {
            "request_id": "request-1",
            "request_kind": kind,
            "prepayment_request_id": "request-1",
            "prepayment_kind": kind,
            "prepayment_transaction_id": transaction_id,
            "payment_admin_doc_message_id": transaction_id,
            "payment_kind": kind,
            "payment_language": "ru",
            "payment_signature": sign_user_payment(settings, user_id, transaction_id, kind, "ru"),
            "payment_offer_time": "2026-08-18T10:00:00+05:00",
        }

        async def get_data(self):
            return dict(self.data)

        async def update_data(self, **kwargs):
            self.data.update(kwargs)

    class Message:
        from_user = SimpleNamespace(id=user_id)

        def __init__(self) -> None:
            self.answers: list[str] = []

        async def answer(self, text: str, **_kwargs: object) -> None:
            self.answers.append(text)

    async def fetch_receipt(_url: str):
        return SimpleNamespace(
            receipt_fingerprint="fiscal-hash-fail",
            transaction_id="RNM:RRN:FP-FAIL",
            amount_kzt=1000,
            seller_bin="",
            rnm="123456789012",
            fp="456789",
        )

    def issues(_receipt, _expected_amount: int, **_kwargs) -> list[str]:
        return []

    async def broken_reserve(**_kwargs):
        raise RuntimeError("db unavailable")

    generated = {"value": False}

    async def generate(**_kwargs):
        generated["value"] = True
        return True

    monkeypatch.setattr(payment_runtime, "get_settings", lambda: settings)
    monkeypatch.setattr(payment_runtime, "fetch_kaspi_ofd_receipt", fetch_receipt)
    monkeypatch.setattr(payment_runtime, "fiscal_receipt_issues", issues)
    monkeypatch.setattr(payment_runtime, "reserve_verified_document_receipt", broken_reserve)
    monkeypatch.setattr(prepayment_runtime, "run_ai_verified_prepayment_generation", generate)

    message = Message()
    asyncio.run(payment_runtime._verify_and_release_fiscal_url(
        message,
        State(),
        "https://receipt.kaspi.kz/web/fiscal?f=123456789012&i=456789&s=1000&t=20260818110000",
    ))

    assert generated["value"] is False
    assert any("Повторно платить не нужно" in text for text in message.answers)


def test_new_request_clears_all_payment_authorization_fields() -> None:
    keys = request_scope._REQUEST_SCOPED_KEYS
    required = {
        "payment_admin_doc_message_id",
        "payment_kind",
        "payment_language",
        "payment_signature",
        "payment_offer_time",
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