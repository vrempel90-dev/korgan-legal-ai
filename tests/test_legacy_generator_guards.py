from __future__ import annotations

import asyncio
import inspect

from korgan import reply_menu_handlers, response_menu_handlers, universal_claim_runtime
from korgan.claim_quality_hotfix import install_runtime_hotfix


def test_legacy_document_helpers_delegate_to_guarded_runtime() -> None:
    contract_source = inspect.getsource(reply_menu_handlers._send_contract_as_word)
    response_source = inspect.getsource(response_menu_handlers._send_response_as_word)

    assert "universal_document_runtime._send_contract" in contract_source
    assert "universal_document_runtime._send_response" in response_source
    assert "answer_document" not in contract_source
    assert "answer_document" not in response_source


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
