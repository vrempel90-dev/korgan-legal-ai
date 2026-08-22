from __future__ import annotations

import asyncio
from types import SimpleNamespace

from korgan.client_document_feedback_hotfix import send_checklist_once
from korgan.client_document_feedback_safe import wrap_ensure_prepayment_with_client_notices
from korgan.request_scope import request_is_current, start_new_document_request


class _State:
    def __init__(self, language: str = "ru") -> None:
        self.data: dict = {"language": language}

    async def get_data(self) -> dict:
        return dict(self.data)

    async def update_data(self, **kwargs) -> None:
        self.data.update(kwargs)

    async def set_data(self, data: dict) -> None:
        self.data = dict(data)


class _Message:
    def __init__(self) -> None:
        self.answers: list[str] = []
        self.documents: list[str] = []
        self.chat = SimpleNamespace(id=123)

    async def answer(self, text: str, **kwargs) -> None:
        self.answers.append(str(text))

    async def answer_document(self, document, **kwargs) -> None:
        self.documents.append(str(document))


async def _authorize_current(message: _Message, state: _State, *, kind: str) -> bool:
    data = await state.get_data()
    return bool(data.get("request_id") and data.get("request_kind") == kind)


def test_all_five_requests_get_fresh_id_correct_kind_and_only_selected_checklist() -> None:
    async def scenario() -> None:
        labels = {
            "claim": "ИСКА",
            "pretrial": "ПРЕТЕНЗИИ",
            "pretrial_response": "ОТВЕТА НА ПРЕТЕНЗИЮ",
            "contract": "ДОГОВОРА",
            "response": "ОТЗЫВА НА ИСК",
        }
        state = _State()
        seen_ids: set[str] = set()
        for kind in labels:
            message = _Message()
            request_id = await start_new_document_request(state, kind=kind, mode=f"{kind}_waiting")
            data = await state.get_data()
            assert request_id
            assert request_id not in seen_ids
            seen_ids.add(request_id)
            assert data["request_id"] == request_id
            assert data["request_kind"] == kind

            sent = await send_checklist_once(message, state, kind)
            assert sent is True
            assert len(message.answers) == 1
            assert labels[kind] in message.answers[0]
            assert await send_checklist_once(message, state, kind) is False
            assert len(message.answers) == 1

    asyncio.run(scenario())


def test_newer_document_makes_old_checklist_and_delivery_scope_silent() -> None:
    async def scenario() -> None:
        state = _State()
        message = _Message()
        old_id = await start_new_document_request(state, kind="claim", mode="universal_claim_waiting")
        assert await send_checklist_once(message, state, "claim") is True
        before = len(message.answers)

        new_id = await start_new_document_request(state, kind="contract", mode="contract_details")
        assert new_id != old_id
        assert not await request_is_current(state, old_id, "claim")
        # The same current-request predicate used by production delivery now
        # rejects the old request, and the notice helper is silent too.
        assert await send_checklist_once(message, state, "claim") is False
        assert len(message.answers) == before
        assert message.documents == []

    asyncio.run(scenario())


def test_progress_is_emitted_only_after_prepayment_authorizes_current_request() -> None:
    async def scenario() -> None:
        state = _State()
        message = _Message()
        await start_new_document_request(state, kind="claim", mode="universal_claim_waiting")

        denied_calls = 0

        async def denied(message, state, *, kind: str) -> bool:
            nonlocal denied_calls
            denied_calls += 1
            return False

        denied_gate = wrap_ensure_prepayment_with_client_notices(denied)
        assert await denied_gate(message, state, kind="claim") is False
        assert denied_calls == 1
        assert any("📋" in text for text in message.answers)
        assert not any("Документ в работе" in text for text in message.answers)

        allowed_gate = wrap_ensure_prepayment_with_client_notices(_authorize_current)
        assert await allowed_gate(message, state, kind="claim") is True
        assert sum("Документ в работе" in text for text in message.answers) == 1
        # A retry of the same immutable request must not spam either notice.
        assert await allowed_gate(message, state, kind="claim") is True
        assert sum("Документ в работе" in text for text in message.answers) == 1
        assert sum("📋" in text for text in message.answers) == 1

    asyncio.run(scenario())


def test_stale_kind_cannot_get_progress_or_authorize_generation() -> None:
    async def scenario() -> None:
        state = _State()
        message = _Message()
        old_id = await start_new_document_request(state, kind="claim", mode="universal_claim_waiting")
        await start_new_document_request(state, kind="response", mode="response_details")

        gate = wrap_ensure_prepayment_with_client_notices(_authorize_current)
        assert await gate(message, state, kind="claim") is False
        assert not await request_is_current(state, old_id, "claim")
        assert not message.answers
        assert not message.documents

    asyncio.run(scenario())
