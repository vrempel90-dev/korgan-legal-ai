"""Старый маршрут отправки юридического документа через Telegram закрыт.

KORGAN выдаёт готовый Word через подписанный document-access/download контур.
Это не позволяет устаревшему клиенту заставить backend переслать приватный
юридический документ через бота. Совместимый endpoint остаётся только затем,
чтобы старый WebView получил явный 410 и перешёл на актуальный download flow.
"""

from __future__ import annotations

import base64

import pytest
from fastapi.testclient import TestClient

from korgan import miniapp_api_v2 as core
from korgan.miniapp_api_recovery_cors import app

DOCX = b"PK\x03\x04 fake docx payload"


@pytest.fixture()
def client(monkeypatch):
    state = {
        "consent": {"accepted": True},
        "cases": {
            "KOR-TEST": {
                "title": "Исковое заявление о взыскании долга",
                "filename": "KORGAN_claim.docx",
                "release_status": "preliminary",
                "document_base64": base64.b64encode(DOCX).decode("ascii"),
            }
        },
    }
    monkeypatch.setattr(core.legacy, "_identity", lambda init_data: "555777")

    async def _consent(identity):
        return state

    monkeypatch.setattr(core.legacy, "_require_consent", _consent)
    return TestClient(app)


def test_retired_telegram_delivery_fails_closed_even_for_ready_document(client):
    response = client.post(
        "/miniapp/cases/KOR-TEST/document/telegram",
        headers={"X-Telegram-Init-Data": "x"},
    )
    assert response.status_code == 410
    detail = response.json()["detail"]
    assert "Telegram отключена" in detail
    assert "KORGAN Mini App" in detail


def test_retired_telegram_delivery_never_exposes_document_bytes(client):
    response = client.post(
        "/miniapp/cases/KOR-TEST/document/telegram",
        headers={"X-Telegram-Init-Data": "x"},
    )
    assert response.status_code == 410
    assert "document_base64" not in response.text
    assert base64.b64encode(DOCX).decode("ascii") not in response.text


def test_retired_telegram_delivery_does_not_probe_case_existence(client):
    """После согласия compatibility-route одинаково закрыт для любого case_id."""
    response = client.post(
        "/miniapp/cases/KOR-UNKNOWN/document/telegram",
        headers={"X-Telegram-Init-Data": "x"},
    )
    assert response.status_code == 410


def test_unsigned_retired_delivery_request_is_still_rejected(client, monkeypatch):
    async def denied(_identity):
        from fastapi import HTTPException

        raise HTTPException(status_code=403, detail="Consent required")

    monkeypatch.setattr(core.legacy, "_require_consent", denied)
    response = client.post(
        "/miniapp/cases/KOR-TEST/document/telegram",
        headers={"X-Telegram-Init-Data": "x"},
    )
    assert response.status_code == 403