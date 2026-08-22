from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace

import korgan.pretrial_response_runtime as pretrial_response_runtime
import korgan.pretrial_runtime as pretrial_runtime
import korgan.universal_claim_runtime as universal_claim_runtime
import korgan.universal_document_runtime as universal_document_runtime
from korgan.document_category_router import PreferredDocumentCategory
from korgan.request_scope import (
    is_main_menu_text,
    request_is_current,
    request_label,
    start_new_document_request,
)


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

    assert result == {"document_category": "claim"}


def test_explicit_request_from_response_waiting_starts_new_category() -> None:
    state = _State({"mode": "response_details"})
    message = SimpleNamespace(text="Подготовь досудебную претензию должнику")

    result = asyncio.run(PreferredDocumentCategory()(message, state))

    assert result == {
        "document_category": "pretrial",
        "document_request_explicit": True,
    }


def test_main_menu_buttons_are_navigation_not_case_materials() -> None:
    assert is_main_menu_text("📄 Документ")
    assert is_main_menu_text("📄 Құжат")
    assert is_main_menu_text("⚖️ Консультация")
    assert is_main_menu_text("💰 Цены")
    assert not is_main_menu_text("Ответчик должен 600 000 тенге")


def test_document_button_is_not_consumed_by_any_waiting_document_flow() -> None:
    ru_document = SimpleNamespace(text="📄 Документ")
    kk_document = SimpleNamespace(text="📄 Құжат")

    claim_state = _State({"mode": "universal_claim_waiting"})
    pretrial_state = _State({"mode": "pretrial_waiting"})
    pretrial_response_state = _State({"mode": "pretrial_response_waiting"})
    contract_state = _State({"mode": "contract_details"})
    response_state = _State({"mode": "response_details"})

    assert asyncio.run(PreferredDocumentCategory()(ru_document, claim_state)) is False
    assert asyncio.run(universal_claim_runtime._ClaimWaiting()(ru_document, claim_state)) is False
    assert asyncio.run(pretrial_runtime._Waiting()(ru_document, pretrial_state)) is False
    assert asyncio.run(pretrial_response_runtime._Waiting()(ru_document, pretrial_response_state)) is False
    assert asyncio.run(universal_document_runtime.ContractDetailsFilter()(ru_document, contract_state)) is False
    assert asyncio.run(universal_document_runtime.ResponseDetailsFilter()(ru_document, response_state)) is False

    assert asyncio.run(PreferredDocumentCategory()(kk_document, claim_state)) is False
    assert asyncio.run(universal_claim_runtime._ClaimWaiting()(kk_document, claim_state)) is False
    assert asyncio.run(pretrial_runtime._Waiting()(kk_document, pretrial_state)) is False
    assert asyncio.run(pretrial_response_runtime._Waiting()(kk_document, pretrial_response_state)) is False
    assert asyncio.run(universal_document_runtime.ContractDetailsFilter()(kk_document, contract_state)) is False
    assert asyncio.run(universal_document_runtime.ResponseDetailsFilter()(kk_document, response_state)) is False


def test_old_request_becomes_stale_as_soon_as_new_document_is_selected() -> None:
    state = _State({"language": "ru", "terms_accepted": True})
    old_id = asyncio.run(
        start_new_document_request(state, kind="pretrial_response", mode="pretrial_response_waiting")
    )
    assert asyncio.run(request_is_current(state, old_id, "pretrial_response")) is True

    new_id = asyncio.run(
        start_new_document_request(state, kind="claim", mode="universal_claim_waiting")
    )
    assert old_id != new_id
    assert asyncio.run(request_is_current(state, old_id, "pretrial_response")) is False
    assert asyncio.run(request_is_current(state, new_id, "claim")) is True


def test_every_generator_has_a_stale_request_release_guard() -> None:
    generators = {
        "claim": universal_claim_runtime._send_claim,
        "pretrial": pretrial_runtime._generate,
        "pretrial_response": pretrial_response_runtime._generate,
        "response": universal_document_runtime._send_response,
        "contract": universal_document_runtime._send_contract,
    }
    for kind, generator in generators.items():
        source = inspect.getsource(generator)
        assert "request_is_current" in source, kind
        assert "STALE_DOCUMENT_SUPPRESSED" in source, kind


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


def test_pretrial_menu_click_only_opens_request_and_never_generates() -> None:
    source = inspect.getsource(pretrial_runtime.pretrial_callback)
    assert "start_new_document_request" in source
    assert "_ask_pretrial(" in source
    assert "_generate(" not in source


def test_all_document_menu_callbacks_only_open_fresh_requests() -> None:
    callbacks = {
        "claim": (
            universal_document_runtime.claim_callback,
            "begin_claim_request(",
            ("_generate_now(", "_send_claim(", "answer_document("),
        ),
        "pretrial": (
            pretrial_runtime.pretrial_callback,
            "_ask_pretrial(",
            ("_generate(", "answer_document("),
        ),
        "pretrial_response": (
            pretrial_response_runtime.pretrial_response_callback,
            "_ask_materials(",
            ("_generate(", "answer_document("),
        ),
        "response": (
            universal_document_runtime.response_callback,
            "_ask_response(",
            ("_send_response(", "answer_document("),
        ),
        "contract": (
            universal_document_runtime.contract_callback,
            "_ask_contract(",
            ("_send_contract(", "answer_document("),
        ),
    }

    for kind, (callback, prompt_call, forbidden_calls) in callbacks.items():
        source = inspect.getsource(callback)
        assert "start_new_document_request" in source, kind
        assert prompt_call in source, kind
        for forbidden in forbidden_calls:
            assert forbidden not in source, f"{kind}: menu click must not call {forbidden}"


def test_fresh_request_labels_are_specific_in_both_languages() -> None:
    assert request_label("claim", "ru") == "Исковое заявление"
    assert request_label("pretrial", "ru") == "Досудебная претензия"
    assert request_label("pretrial_response", "ru") == "Ответ на претензию"
    assert request_label("response", "ru") == "Отзыв на иск"
    assert request_label("contract", "ru") == "Договор"
    assert request_label("claim", "kk") == "Талап қою арызы"
    assert request_label("pretrial_response", "kk") == "Сотқа дейінгі талапқа жауап"
