from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_railway_starts_existing_strict_telegram_agent() -> None:
    procfile = (ROOT / "Procfile").read_text(encoding="utf-8").strip()
    assert procfile == "worker: python -m korgan.strict_bot"


def test_strict_agent_keeps_existing_professional_runtime_and_routes() -> None:
    source = (ROOT / "korgan" / "strict_bot.py").read_text(encoding="utf-8")

    assert "base_bot.service = PretrialProductionService(settings)" in source
    assert "install_professional_rag_bridge()" in source
    assert "install_stable_legal_release()" in source
    assert "install_payment_gate()" in source
    assert "start_corpus_refresh_task()" in source

    required_routers = (
        "admin_router",
        "start_router",
        "safety_router",
        "payment_router",
        "contact_router",
        "consultation_ui_router",
        "pretrial_response_router",
        "kazakh_router",
        "review_cta_router",
        "document_category_router",
        "pretrial_router",
        "universal_claim_router",
        "universal_document_router",
        "reply_menu_router",
        "consultation_quota_router",
        "base_bot.router",
    )
    for router in required_routers:
        assert f"dp.include_router({router})" in source
