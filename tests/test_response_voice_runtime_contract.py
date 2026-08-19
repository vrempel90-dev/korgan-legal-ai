from __future__ import annotations

from pathlib import Path


def test_voice_repair_is_explicitly_limited_to_style() -> None:
    source = Path("korgan/response_voice_guard.py").read_text(encoding="utf-8")
    assert "FACT LOCK" in source
    assert "LAW LOCK" in source
    assert "не меняй факты, суммы, даты, стороны, доказательства и VERIFIED-нормы" in source
    assert "Третье лицо допустимо для описания требований и доводов ПРОТИВНОЙ стороны" in source


def test_voice_guard_fails_closed_if_repair_keeps_bad_voice() -> None:
    source = Path("korgan/response_voice_guard.py").read_text(encoding="utf-8")
    assert "pretrial response voice repair failed" in source
    assert "response to claim voice repair failed" in source
