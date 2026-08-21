from __future__ import annotations

import asyncio
import inspect
from pathlib import Path

from korgan.contract_intent import is_contract_drafting_request
from korgan.document_category_router import PreferredDocumentCategory, preferred_document_category
from korgan.document_section_lock import SelectedDocumentSection, route_selected_document_section
from korgan.request_scope import active_document_kind
from korgan.response_intent import is_response_to_claim_request


class _State:
    def __init__(self, data: dict):
        self.data = dict(data)

    async def get_data(self):
        return dict(self.data)


class _Message:
    def __init__(self, text: str):
        self.text = text


def _selected(kind: str, mode: str, text: str):
    return asyncio.run(
        SelectedDocumentSection()(
            _Message(text),
            _State({"request_id": "req-1", "request_kind": kind, "mode": mode, "language": "ru"}),
        )
    )


def test_user_claim_about_contract_stays_claim_not_contract() -> None:
    text = (
        "Мне нужно подготовить исковое заявление. Я заключил договор на изготовление кухни. "
        "Хочу отказаться от договора и взыскать 1 300 000 тенге. Досудебная претензия была направлена."
    )
    assert preferred_document_category(text) == "claim"
    assert is_contract_drafting_request(text) is False
    assert is_response_to_claim_request(text) is False


def test_contract_fact_is_not_a_contract_drafting_request() -> None:
    assert is_contract_drafting_request("Хочу отказаться от договора и взыскать уплаченные деньги") is False
    assert is_contract_drafting_request("Нужно взыскать задолженность по договору оказания услуг") is False
    assert is_contract_drafting_request("Составь договор оказания услуг") is True
    assert is_contract_drafting_request("Мне нужен договор оказания услуг") is True


def test_response_fact_is_not_a_new_response_request() -> None:
    assert is_response_to_claim_request("Ответчик сообщил, что отзыв на иск уже направлен в суд") is False
    assert is_response_to_claim_request("Подготовь отзыв на исковое заявление") is True
    assert is_response_to_claim_request("Мне нужен отзыв на иск") is True


def test_each_button_owns_its_waiting_section() -> None:
    cases = {
        "claim": "universal_claim_waiting",
        "pretrial": "pretrial_waiting",
        "pretrial_response": "pretrial_response_waiting",
        "response": "response_details",
        "contract": "contract_details",
    }
    text = "По договору была направлена претензия, затем подан иск и получен отзыв."
    for kind, mode in cases.items():
        result = _selected(kind, mode, text)
        assert result == {"selected_document_kind": kind}, kind


def test_screenshot_claim_payload_is_owned_by_claim_button() -> None:
    text = (
        "Мне нужно подготовить исковое заявление. Я заключил с ИП договор на изготовление кухни. "
        "Хочу отказаться от договора и взыскать уплаченную сумму. Претензия была направлена ответчику."
    )
    assert _selected("claim", "universal_claim_waiting", text) == {"selected_document_kind": "claim"}


def test_selected_section_never_reclassifies_case_text() -> None:
    source = inspect.getsource(route_selected_document_section)
    assert "preferred_document_category" not in source
    assert "request_label" not in source
    assert "selected_document_kind == \"claim\"" in source
    assert "selected_document_kind == \"contract\"" in source


def test_section_lock_does_not_capture_other_special_states() -> None:
    assert _selected("claim", "verification_gate", "Согласен") is False
    assert _selected("contract", "main", "Дополнительные сведения") is False


def test_active_button_request_disables_text_category_rerouting() -> None:
    state = _State({
        "request_id": "claim-1",
        "request_kind": "claim",
        "mode": "universal_claim_waiting",
        "language": "ru",
    })
    message = _Message("Составь договор оказания услуг")
    assert asyncio.run(PreferredDocumentCategory()(message, state)) is False
    assert active_document_kind(state.data) == "claim"


def test_production_router_orders_button_lock_before_all_document_intents() -> None:
    source = Path("korgan/strict_bot.py").read_text(encoding="utf-8")
    lock = source.index("dp.include_router(document_section_lock_router)")
    assert lock < source.index("dp.include_router(document_category_router)")
    assert lock < source.index("dp.include_router(pretrial_response_router)")
    assert lock < source.index("dp.include_router(pretrial_router)")
    assert lock < source.index("dp.include_router(universal_claim_router)")
    assert lock < source.index("dp.include_router(universal_document_router)")
