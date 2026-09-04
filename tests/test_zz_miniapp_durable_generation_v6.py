from __future__ import annotations

from korgan import miniapp_api_v6 as v6


def _route(path: str, method: str):
    matches = [
        route
        for route in v6.app.router.routes
        if getattr(route, "path", None) == path
        and method in (getattr(route, "methods", set()) or set())
    ]
    assert len(matches) == 1
    return matches[0]


def test_v6_owns_complete_generation_surface() -> None:
    assert _route("/miniapp/documents/generate", "POST").endpoint is v6.generate_document
    assert _route("/miniapp/documents/generation/{job_id}", "GET").endpoint is v6.generation_status
    assert _route("/miniapp/documents/generation/{job_id}/retry", "POST").endpoint is v6.retry_generation
    assert _route("/miniapp/cases/{case_id}/generation", "GET").endpoint is v6.case_generation
    assert _route("/miniapp/documents/payments/{order_id}/receipt", "POST").endpoint is v6.document_payment_receipt
    assert _route("/miniapp/documents/payments/{order_id}", "GET").endpoint is v6.document_payment_status
    assert _route("/miniapp/documents/payments/{order_id}/retry", "POST").endpoint is v6.retry_paid_document


def test_every_supported_document_type_uses_same_durable_contract() -> None:
    expected = {"claim", "contract", "response", "pretrial", "pretrial_response"}
    assert expected.issubset(v6.core._DOCUMENT_TYPES)

    for document_type in expected:
        case = {
            "id": f"case-{document_type}",
            "description": "Факты дела предоставлены клиентом.",
            "document_type": document_type,
            "language": "ru",
            "materials": [],
            "conversation": [],
        }
        payload = v6.core.GenerateRequest(
            case_id=case["id"],
            document_type=document_type,
            language="ru",
        )
        normalized_type, language, scope = v6._normalize_request(case, payload)
        assert normalized_type == document_type
        assert language == "ru"
        assert len(scope) == 64


def test_generation_job_payload_matches_frontend_state_machine() -> None:
    job = {
        "job_id": "GEN-1",
        "case_id": "case-1",
        "status": "running",
        "stage": "legal_analysis",
        "progress": 42,
        "document_ready": False,
        "retryable": False,
        "error": "",
        "scope": "secret-internal-scope",
        "payment_order_id": 99,
    }
    public = v6._job_public(job)
    assert public == {
        "job_id": "GEN-1",
        "case_id": "case-1",
        "status": "running",
        "stage": "legal_analysis",
        "progress": 42,
        "document_ready": False,
        "retryable": False,
        "error": "",
    }


def test_paid_receipt_route_starts_generation_without_manual_prepare_step() -> None:
    source = open(v6.__file__, encoding="utf-8").read()
    assert '"generation_started": True' in source
    assert "await _start_paid_order(order, x_telegram_init_data)" in source
    assert "Подготовить оплаченный документ" not in source


def test_launcher_uses_v6_runtime() -> None:
    from korgan import miniapp_telegram_launcher as launcher

    source = open(launcher.__file__, encoding="utf-8").read()
    assert 'uvicorn.run("korgan.miniapp_api_v6:app"' in source
