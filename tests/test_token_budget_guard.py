from __future__ import annotations

import os

from korgan.claim_pipeline_v2 import MODE_ENV, claim_pipeline_v2_mode
from korgan.config import Settings
from korgan.token_budget_guard import apply_token_budget_guard


def _settings(**overrides) -> Settings:
    values = {
        "telegram_bot_token": "test-token",
        "openai_api_key": "test-key",
        "monthly_ai_budget_usd": 10.0,
        "token_budget_guard_enabled": True,
        "allow_extra_ai_pipeline_calls": False,
    }
    values.update(overrides)
    return Settings(**values)


def test_four_month_budget_does_not_downgrade_legal_models() -> None:
    settings = _settings()
    assert settings.openai_model == "gpt-5.1"
    assert settings.openai_vision_model == "gpt-5.1"
    assert settings.openai_validation_model == "gpt-5.1"
    assert settings.monthly_ai_budget_usd == 10.0


def test_guard_keeps_default_production_pipeline_off(monkeypatch) -> None:
    monkeypatch.delenv(MODE_ENV, raising=False)
    assert apply_token_budget_guard(_settings()) == "off"
    assert claim_pipeline_v2_mode() == "off"


def test_guard_blocks_accidental_extra_model_calls(monkeypatch) -> None:
    monkeypatch.setenv(MODE_ENV, "active")
    assert apply_token_budget_guard(_settings()) == "off"
    assert os.environ[MODE_ENV] == "off"
    assert claim_pipeline_v2_mode() == "off"


def test_explicit_quality_experiment_can_opt_in(monkeypatch) -> None:
    monkeypatch.setenv(MODE_ENV, "active")
    settings = _settings(allow_extra_ai_pipeline_calls=True)
    assert apply_token_budget_guard(settings) == "active"
    assert claim_pipeline_v2_mode() == "active"


def test_disabled_guard_preserves_operator_choice(monkeypatch) -> None:
    monkeypatch.setenv(MODE_ENV, "observe")
    settings = _settings(token_budget_guard_enabled=False)
    assert apply_token_budget_guard(settings) == "observe"
    assert claim_pipeline_v2_mode() == "observe"
