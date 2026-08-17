"""Блок 4: чек-листы требований. Пропуск пункта без решения = ошибка пайплайна."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from korgan.legal.checklists import (  # noqa: E402
    CHECKLISTS,
    ChecklistIncomplete,
    Decision,
    DisputeType,
    ItemDecision,
    checklist_prompt,
    checklist_schema,
    items_for,
    parse_decisions,
    validate_decisions,
    waived_notes,
)

CONSUMER = DisputeType.CONSUMER_CONTRACTOR


def _all_claimed(dispute_type: DisputeType) -> list[ItemDecision]:
    return [ItemDecision(key=item.key, decision=Decision.CLAIMED) for item in items_for(dispute_type)]


def test_every_dispute_type_has_a_checklist() -> None:
    assert set(CHECKLISTS) == set(DisputeType)
    assert all(CHECKLISTS[dispute] for dispute in DisputeType)


def test_consumer_contractor_covers_the_required_demands() -> None:
    keys = {item.key for item in items_for(CONSUMER)}

    assert {
        "principal_debt",
        "consumer_penalty",
        "money_use_interest",
        "moral_damages",
        "claim_securing",
        "duty_exemption",
        "claimant_venue",
    } <= keys


def test_schema_restricts_keys_and_decisions() -> None:
    schema = checklist_schema(CONSUMER)
    item = schema["properties"]["decisions"]["items"]

    assert item["properties"]["key"]["enum"] == [entry.key for entry in items_for(CONSUMER)]
    assert item["properties"]["decision"]["enum"] == ["claimed", "not_claimed"]
    assert item["required"] == ["key", "decision", "reason"]


def test_prompt_lists_every_item() -> None:
    prompt = checklist_prompt(CONSUMER)

    assert "потребительский подряд" in prompt
    for item in items_for(CONSUMER):
        assert item.key in prompt


def test_full_set_of_decisions_passes() -> None:
    decisions = validate_decisions(CONSUMER, _all_claimed(CONSUMER))

    assert len(decisions) == len(items_for(CONSUMER))


def test_missing_item_fails_the_pipeline() -> None:
    """Молчание про моральный вред — это дефект, а не «видимо, неприменимо»."""
    decisions = [d for d in _all_claimed(CONSUMER) if d.key != "moral_damages"]

    with pytest.raises(ChecklistIncomplete, match="пропущены без решения: моральный вред"):
        validate_decisions(CONSUMER, decisions)


def test_several_missing_items_are_all_named() -> None:
    decisions = [d for d in _all_claimed(CONSUMER) if d.key not in {"duty_exemption", "claimant_venue"}]

    with pytest.raises(ChecklistIncomplete) as exc:
        validate_decisions(CONSUMER, decisions)

    assert "освобождение от государственной пошлины" in str(exc.value)
    assert "альтернативная подсудность" in str(exc.value)


def test_refusal_without_a_reason_fails() -> None:
    decisions = [
        d if d.key != "claim_securing" else ItemDecision(key=d.key, decision=Decision.NOT_CLAIMED)
        for d in _all_claimed(CONSUMER)
    ]

    with pytest.raises(ChecklistIncomplete, match="без причины: обеспечение иска"):
        validate_decisions(CONSUMER, decisions)


def test_refusal_with_a_reason_passes() -> None:
    decisions = [
        d
        if d.key != "claim_securing"
        else ItemDecision(key=d.key, decision=Decision.NOT_CLAIMED, reason="истец не заявлял ходатайство")
        for d in _all_claimed(CONSUMER)
    ]

    result = validate_decisions(CONSUMER, decisions)

    assert not result["claim_securing"].claimed


def test_unknown_key_fails() -> None:
    decisions = [*_all_claimed(CONSUMER), ItemDecision(key="выдуманный_пункт", decision=Decision.CLAIMED)]

    with pytest.raises(ChecklistIncomplete, match="неизвестным пунктам"):
        validate_decisions(CONSUMER, decisions)


def test_waived_notes_explain_what_was_not_claimed() -> None:
    decisions = [
        d
        if d.key != "moral_damages"
        else ItemDecision(key=d.key, decision=Decision.NOT_CLAIMED, reason="истец отказался от требования")
        for d in _all_claimed(CONSUMER)
    ]

    notes = waived_notes(CONSUMER, validate_decisions(CONSUMER, decisions))

    assert notes == ["Не заявлено — моральный вред: истец отказался от требования"]


def test_parse_decisions_drops_malformed_entries() -> None:
    parsed = parse_decisions(
        [
            {"key": "principal_debt", "decision": "claimed", "reason": ""},
            {"key": "", "decision": "claimed", "reason": ""},
            {"key": "moral_damages", "decision": "неизвестно", "reason": ""},
        ]
    )

    assert [d.key for d in parsed] == ["principal_debt"]


def test_parsed_but_incomplete_answer_still_fails_validation() -> None:
    """Модель вернула мусор — пайплайн падает, а не выпускает неполный иск."""
    parsed = parse_decisions([{"key": "principal_debt", "decision": "claimed", "reason": ""}])

    with pytest.raises(ChecklistIncomplete):
        validate_decisions(CONSUMER, parsed)


@pytest.mark.parametrize("dispute", list(DisputeType))
def test_each_dispute_type_validates_its_own_full_set(dispute: DisputeType) -> None:
    assert validate_decisions(dispute, _all_claimed(dispute))
