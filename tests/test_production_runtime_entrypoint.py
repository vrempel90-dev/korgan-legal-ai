from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_procfile_uses_full_strict_professional_runtime() -> None:
    assert _text("Procfile").strip() == "worker: python -m korgan.strict_bot"


def test_strict_runtime_installs_consultation_guard_before_service_creation() -> None:
    source = _text("korgan/strict_bot.py")
    guard = source.index("install_professional_consultation_guard()")
    service = source.index("stable_service = PretrialResponseProductionService(settings)")
    assert guard < service


def test_strict_runtime_builds_canonical_professional_service_chain() -> None:
    source = _text("korgan/strict_bot.py")
    assert "stable_service = PretrialResponseProductionService(settings)" in source
    assert "ClaimServiceMux(stable_service, settings)" in source
    assert "ClaimPipelineV2Adapter(ClaimServiceMux(stable_service, settings))" in source


def test_strict_runtime_exposes_all_core_legal_routes() -> None:
    source = _text("korgan/strict_bot.py")
    required = (
        "consultation_ui_router",
        "pretrial_response_router",
        "pretrial_router",
        "universal_claim_router",
        "universal_document_router",
        "consultation_quota_router",
        "base_bot.router",
    )
    for route in required:
        assert f"dp.include_router({route})" in source


def test_strict_runtime_keeps_source_and_document_safety_layers() -> None:
    source = _text("korgan/strict_bot.py")
    required = (
        "install_professional_rag_bridge()",
        "install_stable_legal_release()",
        "install_professional_consultation_guard()",
        "install_universal_word_quality_guard()",
        "install_universal_word_final_hardening()",
        "install_request_race_guard()",
        "install_document_generator_ownership_guard()",
    )
    for call in required:
        assert call in source
