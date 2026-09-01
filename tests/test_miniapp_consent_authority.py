"""Согласие определяет сервер, а не сохранённый флаг браузера.

Пользователь мог отозвать согласие в другом WebView/на другом устройстве либо
открыть новую версию условий. Клиент должен узнать фактический статус до доступа
к делам и не должен автоматически принять условия только потому, что старый
localStorage содержит ``consentAccepted: true``.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from korgan import miniapp_api_v2 as core
from korgan.miniapp_api_recovery_cors import app
from tests.production_routes import owner


def _client(monkeypatch, state: dict):
    monkeypatch.setattr(core.legacy, "_identity", lambda _init_data: "consent-user")

    async def load(_identity: str):
        return state

    monkeypatch.setattr(core.legacy, "_state", load)
    return TestClient(app)


def test_deployed_app_reports_current_server_consent(monkeypatch) -> None:
    state = {
        "consent": {"accepted": True, "terms_version": "2026-08-16-v1"},
        "cases": {},
    }
    with _client(monkeypatch, state) as client:
        response = client.get("/miniapp/consent", headers={"X-Telegram-Init-Data": "signed"})

    assert response.status_code == 200
    assert response.json() == {
        "accepted": True,
        "terms_version": "2026-08-16-v1",
    }


def test_missing_server_consent_is_reported_without_forbidden_error(monkeypatch) -> None:
    state = {"consent": None, "cases": {}}
    with _client(monkeypatch, state) as client:
        response = client.get("/miniapp/consent", headers={"X-Telegram-Init-Data": "signed"})

    assert response.status_code == 200
    assert response.json() == {"accepted": False, "terms_version": None}


def test_deployed_consent_status_has_one_explicit_owner() -> None:
    assert owner("/miniapp/consent", "GET") == "korgan.miniapp_consent_status.get_consent_status"
