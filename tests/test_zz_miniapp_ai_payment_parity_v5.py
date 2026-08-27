from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from korgan import miniapp_api_v5 as v5
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


def test_v6_keeps_automatic_document_payment_routes() -> None:
    assert _route("/miniapp/documents/generate", "POST").endpoint is v5.generate_document
    assert _route("/miniapp/documents/payments/{order_id}/receipt", "POST").endpoint is v5.document_payment_receipt
    assert _route("/miniapp/documents/payments/{order_id}", "GET").endpoint is v5.document_payment_status
    assert _route("/miniapp/documents/payments/{order_id}/retry", "POST").endpoint is v5.retry_paid_document


def _valid_check(now: datetime, recipient: str) -> SimpleNamespace:
    return SimpleNamespace(
        readable=True,
        looks_like_kaspi=True,
        payment_successful=True,
        amount_kzt=1000,
        date_time=now.isoformat(),
        merchant_or_recipient=recipient,
        receipt_or_transaction_id="QR17262148385",
        suspicious_signals=(),
    )


def test_real_kaspi_merchant_branch_suffix_is_accepted(monkeypatch) -> None:
    monkeypatch.setattr(v6.settings, "kaspi_payment_recipient", "YSA EDUCATION|ИП YSA EDUCATION")
    now = datetime.now(timezone.utc)
    valid = _valid_check(now, "YSA education на Кунаева")
    assert v6._strict_receipt_issues(valid, 1000, offered_at=now) == []


def test_wrong_recipient_still_fails(monkeypatch) -> None:
    monkeypatch.setattr(v6.settings, "kaspi_payment_recipient", "YSA EDUCATION|ИП YSA EDUCATION")
    now = datetime.now(timezone.utc)
    wrong = _valid_check(now, "Other merchant")
    assert any("получатель" in issue for issue in v6._strict_receipt_issues(wrong, 1000, offered_at=now))


def test_suspicious_receipt_still_fails(monkeypatch) -> None:
    monkeypatch.setattr(v6.settings, "kaspi_payment_recipient", "YSA EDUCATION")
    now = datetime.now(timezone.utc)
    suspicious = _valid_check(now, "ИП YSA EDUCATION")
    suspicious.suspicious_signals = ("edited",)
    assert any("аномалии" in issue for issue in v6._strict_receipt_issues(suspicious, 1000, offered_at=now))


def test_payment_payload_requires_no_admin_confirmation() -> None:
    order = SimpleNamespace(
        id=1,
        case_id="case-1",
        document_type="claim",
        amount_kzt=1000,
        status="approved",
        decision_note="AI receipt verification passed",
    )
    payload = v5._payment_payload(order)
    assert payload["approval_required"] is False
    assert payload["status"] == "approved"
