from __future__ import annotations

import asyncio
import inspect

from korgan import reply_menu_handlers, response_menu_handlers, universal_claim_runtime, universal_document_runtime
from korgan.claim_quality_hotfix import install_runtime_hotfix


def test_legacy_document_helpers_delegate_to_guarded_runtime(monkeypatch) -> None:
    calls: list[tuple[str, object, object]] = []

    async def guarded_contract(message, state) -> None:
        calls.append(("contract", message, state))

    async def guarded_response(message, state) -> None:
        calls.append(("response", message, state))

    monkeypatch.setattr(universal_document_runtime, "_send_contract", guarded_contract)
    monkeypatch.setattr(universal_document_runtime, "_send_response", guarded_response)

    contract_message, contract_state = object(), object()
    response_message, response_state = object(), object()
    asyncio.run(reply_menu_handlers._send_contract_as_word(contract_message, contract_state))
    asyncio.run(response_menu_handlers._send_response_as_word(response_message, response_state))

    assert calls == [
        ("contract", contract_message, contract_state),
        ("response", response_message, response_state),
    ]


def test_claim_hotfix_suppresses_a_stale_request_before_delivery() -> None:
    class State:
        async def get_data(self):
            return {"request_id": "new-request", "request_kind": "claim"}

    class Message:
        async def answer(self, *args, **kwargs):
            raise AssertionError("stale request emitted a response")

        async def answer_document(self, *args, **kwargs):
            raise AssertionError("stale request released a document")

    install_runtime_hotfix()
    parameters = inspect.signature(universal_claim_runtime._send_claim).parameters
    assert "request_id" in parameters

    asyncio.run(
        universal_claim_runtime._send_claim(
            Message(),
            State(),
            context="",
            research=None,
            draft=None,
            request_id="old-request",
        )
    )
