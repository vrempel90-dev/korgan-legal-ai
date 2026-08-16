from pathlib import Path


def test_strict_bot_uses_contract_generation_hotfix() -> None:
    source = Path("korgan/strict_bot.py").read_text(encoding="utf-8")
    assert "from korgan.contract_generation_hotfix import ProductionOpenAILegalService" in source
