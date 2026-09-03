"""Путь клиента проверяется на том приложении, которое запускается в бою.

Слоёв у Mini App API много, и каждый следующий снимает часть маршрутов
предыдущего. Смоук проверяет собранное приложение
`miniapp_api_recovery_cors:app`, которое поднимает ASGI-сервер.

Здесь проходится весь путь на подписанном initData: запуск, шлюз согласия,
согласие, дело, состояние подготовки, безопасная выдача документа, удаление
дела и удаление всех данных.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

from fastapi.testclient import TestClient

from korgan import miniapp_api
from korgan.miniapp_api_recovery_cors import app

TERMS_VERSION = "2026-08-16-v1"


def _init_data(user_id: int) -> str:
    pairs = {
        "auth_date": str(int(time.time())),
        "query_id": "korgan-client-journey",
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


def _headers(user_id: int) -> dict[str, str]:
    return {"X-Telegram-Init-Data": _init_data(user_id)}


def test_client_journey_from_launch_to_removed_data() -> None:
    headers = _headers(-900000801)

    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"
        assert health.json()["legal_runtime"] == "strict_bot"

        parity = client.get("/miniapp/parity", headers=headers)
        assert parity.status_code == 200
        assert parity.json()["status"] == "ok"

        consent = client.get("/miniapp/consent", headers=headers)
        assert consent.status_code == 200
        assert consent.json()["accepted"] is False

        assert client.get("/miniapp/cases", headers=headers).status_code == 403
        assert client.get("/miniapp/pricing", headers=headers).status_code == 403

        accepted = client.post(
            "/miniapp/consent",
            headers=headers,
            json={"accepted": True, "terms_version": TERMS_VERSION},
        )
        assert accepted.status_code == 200
        assert accepted.json()["accepted"] is True
        assert client.get("/miniapp/consent", headers=headers).json() == {
            "accepted": True,
            "terms_version": TERMS_VERSION,
        }
        assert client.get("/miniapp/pricing", headers=headers).status_code == 200

        created = client.post(
            "/miniapp/cases",
            headers=headers,
            json={
                "description": "Заказчик не оплатил выполненные работы по договору.",
                "document_type": "claim",
                "language": "ru",
            },
        )
        assert created.status_code == 200
        case = created.json()["case"]
        case_id = case["id"]
        assert case["status"] == "created"
        assert case["has_document"] is False
        assert case["filing_ready"] is False
        assert case["release_status"] == "not_generated"

        listed = client.get("/miniapp/cases", headers=headers)
        assert listed.status_code == 200
        assert [item["id"] for item in listed.json()["cases"]] == [case_id]

        detail = client.get(f"/miniapp/cases/{case_id}", headers=headers)
        assert detail.status_code == 200

        generation = client.get(f"/miniapp/cases/{case_id}/generation", headers=headers)
        assert generation.status_code == 200
        assert generation.json()["job"] is None

        # Новый безопасный путь выдачи не создаёт ссылку до готовности.
        assert client.post(f"/miniapp/cases/{case_id}/document/access", headers=headers).status_code == 404
        # Старый Telegram-delivery endpoint оставлен только как fail-closed
        # compatibility route и не раскрывает существование/содержимое файла.
        assert client.post(f"/miniapp/cases/{case_id}/document/telegram", headers=headers).status_code == 410

        deleted = client.delete(f"/miniapp/cases/{case_id}", headers=headers)
        assert deleted.status_code == 200
        assert client.get("/miniapp/cases", headers=headers).json()["cases"] == []
        assert client.get(f"/miniapp/cases/{case_id}", headers=headers).status_code == 404

        assert client.delete("/miniapp/me", headers=headers).status_code == 200


def test_unsigned_request_is_refused_by_the_deployed_app() -> None:
    with TestClient(app) as client:
        assert client.get("/miniapp/cases").status_code == 401


def test_document_download_link_cannot_be_forged() -> None:
    with TestClient(app) as client:
        response = client.get("/miniapp/document/download", params={"token": "not-a-real-token"})

    assert response.status_code == 403


def test_case_of_one_user_is_invisible_to_another() -> None:
    owner = _headers(-900000802)
    stranger = _headers(-900000803)

    with TestClient(app) as client:
        for headers in (owner, stranger):
            client.post(
                "/miniapp/consent",
                headers=headers,
                json={"accepted": True, "terms_version": TERMS_VERSION},
            )

        created = client.post(
            "/miniapp/cases",
            headers=owner,
            json={"description": "Спор по договору подряда.", "document_type": "claim", "language": "ru"},
        )
        case_id = created.json()["case"]["id"]

        try:
            assert client.get(f"/miniapp/cases/{case_id}", headers=stranger).status_code == 404
            assert client.get("/miniapp/cases", headers=stranger).json()["cases"] == []
        finally:
            client.delete("/miniapp/me", headers=owner)
            client.delete("/miniapp/me", headers=stranger)