from __future__ import annotations

from sitecustomize import _apply_korgan_gpt56_policy


def test_consultation_is_latency_first_and_has_safe_budget() -> None:
    original = {
        "model": "gpt-5.6-sol",
        "prompt_cache_key": "korgan:korgan_consult_research:v4",
        "max_output_tokens": 1600,
        "text": {"format": {"type": "json_schema"}},
        "tools": [{"type": "web_search", "search_context_size": "medium"}],
    }

    patched = _apply_korgan_gpt56_policy(original)

    assert patched["reasoning"] == {"effort": "none"}
    assert patched["max_output_tokens"] == 2400
    assert patched["text"]["verbosity"] == "low"
    assert patched["tools"][0]["search_context_size"] == "low"
    assert original["max_output_tokens"] == 1600
    assert original["tools"][0]["search_context_size"] == "medium"


def test_document_drafting_keeps_reasoning_but_uses_low_effort() -> None:
    patched = _apply_korgan_gpt56_policy(
        {
            "model": "gpt-5.6-sol",
            "prompt_cache_key": "korgan:korgan_contract_draft:v4",
            "max_output_tokens": 5200,
            "text": {"format": {"type": "json_schema"}},
        }
    )

    assert patched["reasoning"] == {"effort": "low"}
    assert patched["max_output_tokens"] == 6500
    assert patched["text"]["verbosity"] == "medium"


def test_non_korgan_requests_are_untouched() -> None:
    original = {"model": "gpt-5.6-sol", "max_output_tokens": 100}
    assert _apply_korgan_gpt56_policy(original) == original
