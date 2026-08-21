from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace

import korgan.pretrial_response_runtime as pretrial_response_runtime
import korgan.pretrial_runtime as pretrial_runtime
import korgan.universal_claim_runtime as universal_claim_runtime
import korgan.universal_document_runtime as universal_document_runtime
from korgan.document_category_router import PreferredDocumentCategory
from korgan.request_scope import request_label, start_new_document_request


class _State:
    def __init__(self, data: dict):
        self.data = dict(data)

    async def get_data(self):
        return dict(self.data)

    async def set_data(self, data):
        self.data = dict(data)

    async def update_data(self, **kwargs):
        self.data.update(kwargs)


def test_new_document_request_clears_only_case_scope() -> None:
    state = _State(
        {
            "language": "ru",
            "terms_accepted": True,
            "terms_version": "2026-08-16-v1",
            "privacy_consent": True,
            "documents": ["OLD DOC"],
            "facts": ["OLD FACT"],
            "consulted_articles": ["OLD LAW"],
            "claim_draft": {"old": True},
            "pending_fields": ["old"],
            "mode": "response_details",
            "some_session_setting": "keep-me",
        }
    )

    request_id = asyncio.run(
        start_new_document_request(state, kind="claim", mode="universal_claim_waiting")
    )

    assert state.data["documents"] == []
    assert state.data["facts"] == []
    assert state.data["consulted_articles"] == []
    assert state.data["mode"] == "universal_claim_waiting"
    assert state.data["request_kind"] == "claim"
    assert state.data["request_id"] == request_id
    assert state.data["request_started_at"]
    assert "claim_draft" not in state.data
    assert "pending_fields" not in state.data

    # Consent, language and unrelated session settings must survive a new case.
    assert state.data["language"] == "ru"
    assert state.data["terms_accepted"] is True
    assert state.data["privacy_consent"] is True
    assert state.data["some_session_setting"] == "keep-me"


def test_each_new_request_gets_a_new_id() -> None:
    state = _State({"language": "ru", "terms_accepted": True})
    first = asyncio.run(start_new_document_request(state, kind="claim", mode="universal_claim_waiting"))
    state.data["facts"] = ["FIRST CASE"]
    second = asyncio.run(start_new_document_request(state, kind="response", mode="response_details"))

    assert first != second
    assert state.data["facts"] == []
    assert state.data["request_kind"] == "response"


def test_explicit_new_document_request_overrides_old_claim_waiting_mode() -> None:
    state = _State({"mode": "universal_claim_waiting"})
    message = SimpleNamespace(text="Подготовь договор оказания услуг")

    result = asyncio.run(PreferredDocumentCategory()(message, state))

    assert result == {
        "document_category": "contract",
        "document_request_explicit": True,
    }


def test_plain_details_stay_in_current_claim_request() -> None:
    state = _State({"mode": "universal_claim_waiting"})
    message = SimpleNamespace(text="Ответчик должен 600 000 тенге по договору поставки")

    result = asyncio.run(PreferredDocumentCategory()(message, state))

    assert result == {
        "document_category": "claim",
        "document_request_explicit": False,
    }


def test_explicit_request_from_response_waiting_starts_new_category() -> None:
    state = _State({"mode": "response_details"})
    message = SimpleNamespace(text="Подготовь досудебную претензию должнику")

    result = asyncio.run(PreferredDocumentCategory()(message, state))

    assert result == {
        "document_category": "pretrial",
        "document_request_explicit": True,
    }


def test_user_facing_generating_banners_are_removed() -> None:
    source = "\n".join(
        [
            inspect.getsource(universal_claim_runtime._generate_now),
            inspect.getsource(universal_document_runtime._send_contract),
            inspect.getsource(universal_document_runtime._send_response),
            inspect.getsource(pretrial_runtime._generate),
            inspect.getsource(pretrial_response_runtime._generate),
        ]
    )
    assert "Формирую и проверяю" not in source
    assert "Формирую досудебную" not in source
    assert "Анализирую претензию" not in source
    assert "send_chat_action" in source


def test_fresh_request_labels_are_specific_in_both_languages() -> None:
    assert request_label("claim", "ru") == "Исковое заявление"
    assert request_label("pretrial", "ru") == "Досудебная претензия"
    assert request_label("pretrial_response", "ru") == "Ответ на претензию"
    assert request_label("response", "ru") == "Отзыв на иск"
    assert request_label("contract", "ru") == "Договор"
    assert request_label("claim", "kk") == "Талап қою арызы"
    assert request_label("pretrial_response", "kk") == "Сотқа дейінгі талапқа жауап"
