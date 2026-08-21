from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from korgan.document_category_router import preferred_document_category
from korgan.document_generator_ownership_guard import (
    _guard_generator,
    _guard_natural_filter,
    generator_owns_current_request,
    natural_intent_allowed,
)


class _State:
    def __init__(self, data: dict):
        self.data = dict(data)

    async def get_data(self):
        return dict(self.data)


def test_exact_claim_case_with_contract_and_pretrial_facts_is_still_claim() -> None:
    text = (
        "Мне нужно подготовить исковое заявление. "
        "Я заключил договор на изготовление кухонного гарнитура. "
        "25 марта 2026 года я направил письменную досудебную претензию. "
        "Хочу отказаться от договора и взыскать 1 300 000 тенге."
    )
    assert preferred_document_category(text) == "claim"


def test_active_button_request_disables_every_natural_document_intent() -> None:
    active_claim = {
        "request_id": "claim-req-1",
        "request_kind": "claim",
        "mode": "universal_claim_waiting",
    }
    assert natural_intent_allowed(active_claim) is False
    assert natural_intent_allowed({}) is True


def test_generator_ownership_requires_matching_request_kind() -> None:
    assert asyncio.run(
        generator_owns_current_request(
            _State({"request_id": "r1", "request_kind": "claim"}),
            "claim",
        )
    ) is True
    assert asyncio.run(
        generator_owns_current_request(
            _State({"request_id": "r1", "request_kind": "claim"}),
            "pretrial",
        )
    ) is False


def test_guarded_natural_filter_cannot_steal_active_claim() -> None:
    class DummyFilter:
        async def __call__(self, message, state):
            return True

    _guard_natural_filter(DummyFilter)
    active_claim = _State(
        {"request_id": "claim-req-1", "request_kind": "claim", "mode": "universal_claim_waiting"}
    )
    empty = _State({})
    message = SimpleNamespace(text="Подготовь досудебную претензию")

    assert asyncio.run(DummyFilter()(message, active_claim)) is False
    assert asyncio.run(DummyFilter()(message, empty)) is True


def test_wrong_generator_is_blocked_before_original_function_runs() -> None:
    calls: list[str] = []

    async def original(message, state):
        calls.append("called")
        return "ok"

    module = SimpleNamespace(run=original)
    _guard_generator(module, "run", "pretrial")

    claim_state = _State(
        {"request_id": "claim-req-1", "request_kind": "claim", "mode": "universal_claim_waiting"}
    )
    result = asyncio.run(module.run(SimpleNamespace(), claim_state))
    assert result is None
    assert calls == []

    pretrial_state = _State(
        {"request_id": "pretrial-req-1", "request_kind": "pretrial", "mode": "pretrial_waiting"}
    )
    result = asyncio.run(module.run(SimpleNamespace(), pretrial_state))
    assert result == "ok"
    assert calls == ["called"]


def test_production_installs_ownership_guard_before_prepayment_wrapper() -> None:
    source = Path("korgan/strict_bot.py").read_text(encoding="utf-8")
    ownership = source.index("install_document_generator_ownership_guard()")
    prepayment = source.index("install_generation_prepayment_gate()")
    assert ownership < prepayment
