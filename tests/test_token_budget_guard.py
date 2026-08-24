from __future__ import annotations

import os

from korgan.config import Settings
from korgan.token_budget_guard import apply_token_budget_guard


def _settings(**overrides):
    data = {
        "telegram_bot_token": "test",
        "openai_api_key": "test",
        "openai_model": "gpt-5.6-sol",
        "openai_vision_model": "gpt-5.6-luna",
        "openai_validation_model": "gpt-5.6-terra",
        "monthly_ai_budget_usd": 15.50,
        "daily_ai_budget_usd": 0.50,
        "token_budget_guard_enabled": True,
        "allow_extra_ai_pipeline_calls": False,
    }
    data.update(overrides)
    return Settings(**data)


def test_budget_guard_keeps_legal_models_unchanged(monkeypatch):
    settings = _settings()
    monkeypatch.setenv("KORGAN_CLAIM_PIPELINE_V2_MODE", "active")

    result = apply_token_budget_guard(settings)

    assert result == "off"
    assert os.environ["KORGAN_CLAIM_PIPELINE_V2_MODE"] == "off"
    assert settings.openai_model == "gpt-5.6-sol"
    assert settings.openai_vision_model == "gpt-5.6-luna"
    assert settings.openai_validation_model == "gpt-5.6-terra"


def test_explicit_extra_pipeline_opt_in_is_preserved(monkeypatch):
    settings = _settings(allow_extra_ai_pipeline_calls=True)
    monkeypatch.setenv("KORGAN_CLAIM_PIPELINE_V2_MODE", "active")

    assert apply_token_budget_guard(settings) == "active"
    assert os.environ["KORGAN_CLAIM_PIPELINE_V2_MODE"] == "active"


def test_disabled_budget_guard_preserves_operator_mode(monkeypatch):
    settings = _settings(token_budget_guard_enabled=False)
    monkeypatch.setenv("KORGAN_CLAIM_PIPELINE_V2_MODE", "observe")

    assert apply_token_budget_guard(settings) == "observe"
    assert os.environ["KORGAN_CLAIM_PIPELINE_V2_MODE"] == "observe"
