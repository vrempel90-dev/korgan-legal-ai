from __future__ import annotations

from traceback import FrameSummary

import korgan_legal_ai.telegram.runtime as runtime_module
from korgan_legal_ai.telegram.runtime import TelegramRuntime


def test_safe_exception_diagnostics_identifies_research_without_exception_text(monkeypatch) -> None:
    frames = [
        FrameSummary(
            "/app/src/korgan_legal_ai/orchestration/debt_claim.py",
            70,
            "run",
        ),
        FrameSummary(
            "/app/src/korgan_legal_ai/research/gateway.py",
            112,
            "research_locator",
        ),
    ]
    monkeypatch.setattr(runtime_module.traceback, "extract_tb", lambda tb: frames)

    try:
        raise RuntimeError("private case text must never enter diagnostics")
    except RuntimeError as exc:
        stage, location, cause_type = TelegramRuntime._safe_exception_diagnostics(exc)

    assert stage == "legal_research"
    assert location == "korgan_legal_ai/research/gateway.py:research_locator:112"
    assert cause_type == "none"
    diagnostic = f"{stage} {location} {cause_type}"
    assert "private case text" not in diagnostic


def test_safe_exception_diagnostics_reports_only_cause_class(monkeypatch) -> None:
    frames = [
        FrameSummary(
            "/app/src/korgan_legal_ai/fact_lock/service.py",
            42,
            "lock",
        )
    ]
    monkeypatch.setattr(runtime_module.traceback, "extract_tb", lambda tb: frames)

    try:
        try:
            raise ValueError("provider response with sensitive payload")
        except ValueError as cause:
            raise RuntimeError("outer sensitive message") from cause
    except RuntimeError as exc:
        stage, location, cause_type = TelegramRuntime._safe_exception_diagnostics(exc)

    assert stage == "fact_lock"
    assert location == "korgan_legal_ai/fact_lock/service.py:lock:42"
    assert cause_type == "ValueError"
