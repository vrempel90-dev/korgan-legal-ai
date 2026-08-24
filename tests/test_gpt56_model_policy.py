from __future__ import annotations

import pytest
from pydantic import ValidationError

from korgan.config import Settings


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "telegram_bot_token": "test-token",
        "openai_api_key": "test-key",
    }
    values.update(overrides)
    return Settings(**values)


def test_default_model_roles_are_gpt56_only() -> None:
    settings = _settings()
    assert settings.openai_model == "gpt-5.6-sol"
    assert settings.openai_validation_model == "gpt-5.6-terra"
    assert settings.openai_vision_model == "gpt-5.6-luna"
    assert settings.monthly_ai_budget_usd == pytest.approx(15.50)
    assert settings.daily_ai_budget_usd == pytest.approx(0.50)
    assert settings.allow_extra_ai_pipeline_calls is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("openai_model", "gpt-5.1"),
        ("openai_validation_model", "gpt-5.1"),
        ("openai_vision_model", "gpt-5.1"),
        ("openai_model", "gpt-5.6-terra"),
        ("openai_validation_model", "gpt-5.6-sol"),
        ("openai_vision_model", "gpt-5.6-sol"),
    ],
)
def test_model_role_drift_fails_closed(field: str, value: str) -> None:
    with pytest.raises(ValidationError, match="refusing model drift"):
        _settings(**{field: value})
