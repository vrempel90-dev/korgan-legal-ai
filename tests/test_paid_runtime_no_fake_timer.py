from __future__ import annotations

from pathlib import Path


def test_paid_progress_runtime_contains_no_elapsed_time_progress_loop() -> None:
    source = Path("korgan/miniapp_paid_generation_progress_runtime.py").read_text(encoding="utf-8")

    # The only timeout in this runtime is a final telemetry flush ceiling. User
    # progress itself must come from generation_progress.report boundaries.
    assert "generation_progress.report" in source
    assert "sleep(" not in source
    assert "setInterval" not in source
