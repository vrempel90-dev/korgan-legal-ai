from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from korgan import reply_menu_handlers, response_menu_handlers, universal_document_runtime


def test_legacy_contract_sender_delegates_to_guarded_runtime(monkeypatch) -> None:
    guarded = AsyncMock()
    monkeypatch.setattr(universal_document_runtime, "_send_contract", guarded)
    message = object()
    state = object()

    asyncio.run(reply_menu_handlers._send_contract_as_word(message, state))

    guarded.assert_awaited_once_with(message, state)


def test_legacy_response_sender_delegates_to_guarded_runtime(monkeypatch) -> None:
    guarded = AsyncMock()
    monkeypatch.setattr(universal_document_runtime, "_send_response", guarded)
    message = object()
    state = object()

    asyncio.run(response_menu_handlers._send_response_as_word(message, state))

    guarded.assert_awaited_once_with(message, state)
