from __future__ import annotations

from pathlib import Path


def test_production_recovery_stack_loads_paid_handoff_and_real_progress() -> None:
    source = Path("korgan/miniapp_api_recovery_cors.py").read_text(encoding="utf-8")

    assert "miniapp_paid_generation_progress_runtime" in source
    assert "miniapp_paid_receipt_handoff_runtime" in source
    assert source.index("miniapp_paid_autostart_runtime") < source.index("miniapp_paid_receipt_handoff_runtime")
    assert source.index("miniapp_paid_receipt_handoff_runtime") < source.index("miniapp_payment_hardening_runtime")
