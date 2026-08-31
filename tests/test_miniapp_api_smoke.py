from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

from fastapi.testclient import TestClient

from korgan import miniapp_api


def _telegram_init_data(user_id: int = -900000001) -> str:
    pairs = {
        "auth_date": str(int(time.time())),
        "query_id": "korgan-miniapp-smoke",
        "user": json.dumps(
            {"id": user_id, "first_name": "KORGAN", "language_code": "ru"},
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    }
    data_check_string = "\n".join(f"{key}={pairs[key]}" for key in sorted(pairs))
    secret_key = hmac.new(
        b"WebAppData",
        miniapp_api.settings.telegram_bot_token.encode(),
        hashlib.sha256,
    ).digest()
    pairs["hash"] = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(pairs)


def test_authenticated_case_lifecycle_without_ai_calls() -> None:
    headers = {"X-Telegram-Init-Data": _telegram_init_data()}
    with TestClient(miniapp_api.app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"
        assert health.json()["state_encryption"] == "AES-256-GCM"
        # На Railway DATABASE_URL задан, и хранилище обязано быть postgres:
        # состояние «Моих дел» не должно жить в памяти процесса. Локально, без
        # базы, тот же инвариант проверяется в обратную сторону — health не
        # имеет права рапортовать postgres без открытого пула.
        expected_storage = "postgres" if miniapp_api.settings.database_url.strip() else "memory"
        assert health.json()["storage"] == expected_storage

        accepted = client.post(
            "/miniapp/consent",
            headers=headers,
            json={"accepted": True, "terms_version": "2026-08-16-v1"},
        )
        assert accepted.status_code == 200

        created = client.post(
            "/miniapp/cases",
            headers=headers,
            json={
                "description": "Тестовая поставка. Этот кейс не вызывает OpenAI.",
                "document_type": "claim",
                "language": "ru",
            },
        )
        assert created.status_code == 200
        case_id = created.json()["case"]["id"]

        listed = client.get("/miniapp/cases", headers=headers)
        assert listed.status_code == 200
        assert any(item["id"] == case_id for item in listed.json()["cases"])

        detail = client.get(f"/miniapp/cases/{case_id}", headers=headers)
        assert detail.status_code == 200
        assert detail.json()["case"]["document_type"] == "claim"
        assert detail.json()["case"]["conversation"] == []

        removed = client.delete(f"/miniapp/cases/{case_id}", headers=headers)
        assert removed.status_code == 200
        assert removed.json()["ok"] is True

        wiped = client.delete("/miniapp/me", headers=headers)
        assert wiped.status_code == 200
        assert wiped.json()["ok"] is True


def test_ai_history_is_not_used_as_drafting_fact_context() -> None:
    case = {
        "description": "Пользователь сообщил основной факт.",
        "materials": [{"context": "Договор №1 от пользователя."}],
        "conversation": [
            {"role": "user", "text": "Пользователь уточнил сумму 100 000 ₸."},
            {"role": "ai", "text": "AI придумал неподтверждённый штраф 999 999 ₸."},
        ],
    }
    context = miniapp_api._case_context(case)
    assert "Пользователь сообщил основной факт" in context
    assert "Договор №1" in context
    assert "Пользователь уточнил сумму 100 000 ₸" in context
    assert "AI придумал неподтверждённый штраф" not in context


def test_invalid_telegram_signature_is_rejected() -> None:
    headers = {"X-Telegram-Init-Data": "auth_date=1&user=%7B%22id%22%3A1%7D&hash=bad"}
    with TestClient(miniapp_api.app) as client:
        response = client.get("/miniapp/cases", headers=headers)
    assert response.status_code == 401
