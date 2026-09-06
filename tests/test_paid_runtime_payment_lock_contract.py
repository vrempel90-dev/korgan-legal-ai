from __future__ import annotations

from pathlib import Path


def test_receipt_handoff_replaces_locked_inner_target_not_public_route() -> None:
    source = Path("korgan/miniapp_paid_receipt_handoff_runtime.py").read_text(encoding="utf-8")

    assert "idempotency._ORIGINAL_RUN_APPROVED_DOCUMENT = _durable_run_approved_document" in source
    assert "v5._run_approved_document =" not in source
