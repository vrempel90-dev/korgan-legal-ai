"""Документ должен доходить до пользователя внутри Telegram.

Мини-апп открывается во встроенном браузере Telegram, а он блокирует
сохранение файла через blob и <a download>: клик проходит, файла нет,
ошибки тоже нет. В логах это выглядело так — документ сгенерирован,
GET /miniapp/cases/.../document отвечает 200 подряд, а пользователь
сказать, что скачать не может. Надёжный путь — послать файл ботом в чат.
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


def _telegram_stub(monkeypatch, *, ok=True, status=200, description=""):
    sent = {}

    class _Response:
        status_code = status

        @staticmethod
        def json():
            return {"ok": ok, "description": description}

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, data=None, files=None):
            sent["url"] = url
            sent["data"] = data
            sent["files"] = files
            return _Response()

    import korgan.miniapp_telegram_delivery as delivery

    monkeypatch.setattr(delivery.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(delivery, "get_settings", lambda: type("S", (), {"telegram_bot_token": "123:test"})())
    return sent


def test_document_is_sent_to_the_users_private_chat(client, monkeypatch):
    sent = _telegram_stub(monkeypatch)
    response = client.post("/miniapp/cases/KOR-TEST/document/telegram", headers={"X-Telegram-Init-Data": "x"})
    assert response.status_code == 200, response.text
    assert response.json()["ok"] is True
    assert "sendDocument" in sent["url"]
    # chat_id личного чата — это идентификатор пользователя из подписанной initData
    assert sent["data"]["chat_id"] == "555777"
    filename, payload, mime = sent["files"]["document"]
    assert filename == "KORGAN_claim.docx"
    assert payload == DOCX
    assert "wordprocessingml" in mime


def test_preliminary_document_is_labelled_in_the_caption(client, monkeypatch):
    sent = _telegram_stub(monkeypatch)
    client.post("/miniapp/cases/KOR-TEST/document/telegram", headers={"X-Telegram-Init-Data": "x"})
    assert "предварительный проект" in sent["data"]["caption"].lower()


def test_missing_document_is_not_reported_as_success(client, monkeypatch):
    _telegram_stub(monkeypatch)
    response = client.post("/miniapp/cases/KOR-UNKNOWN/document/telegram", headers={"X-Telegram-Init-Data": "x"})
    assert response.status_code == 404


def test_user_who_never_started_the_bot_gets_a_usable_instruction(client, monkeypatch):
    """Бот не может написать первым — пользователю нужно понятное действие."""
    _telegram_stub(monkeypatch, ok=False, status=403, description="Forbidden: bot can't initiate conversation with a user")
    response = client.post("/miniapp/cases/KOR-TEST/document/telegram", headers={"X-Telegram-Init-Data": "x"})
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "Старт" in detail and "KORGAN" in detail


def test_telegram_failure_is_not_silently_swallowed(client, monkeypatch):
    _telegram_stub(monkeypatch, ok=False, status=400, description="Bad Request: wrong file identifier")
    response = client.post("/miniapp/cases/KOR-TEST/document/telegram", headers={"X-Telegram-Init-Data": "x"})
    assert response.status_code == 502
