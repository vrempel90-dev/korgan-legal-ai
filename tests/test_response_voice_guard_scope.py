from __future__ import annotations

from pathlib import Path


def test_guard_scope_names_only_two_defensive_documents() -> None:
    source = Path("korgan/response_voice_guard.py").read_text(encoding="utf-8")
    assert "pretrial_response" in source
    assert "response_to_claim" in source
    assert "No claim, pre-trial demand, contract, consultation, routing or payment logic" in source
