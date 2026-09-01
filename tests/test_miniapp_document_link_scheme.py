"""Ссылка на документ выдаётся по https, иначе клиент её не примет.

Адрес для скачивания собирается из заголовков прокси. Схему брали из
`X-Forwarded-Proto`, а при его отсутствии — из схемы соединения, которая внутри
контейнера всегда `http`. Для домена `*.up.railway.app` это подменялось на
`https` вручную, для собственного домена KORGAN — нет.

Отказ при этом молчаливый и полный. Mini App принимает только `https://` и на
`http://` показывает «Ссылка на документ не получена», причём документ готов и
оплачен, а в логах сервера остаётся успешная выдача ссылки. Внешний адрес
без шифрования и не должен выдаваться: по нему уходит подписанный токен.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient

from korgan import miniapp_api
from korgan import miniapp_api_v2 as core
from korgan.miniapp_api_recovery_cors import app

CASE_ID = "KOR-LINK-0001"


def _init_data(user_id: int = -900000911) -> str:
    pairs = {
        "auth_date": str(int(time.time())),
        "query_id": "korgan-document-link",
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


@pytest.fixture()
def ready_case(monkeypatch) -> None:
    state: dict[str, Any] = {
        "consent": {"accepted": True, "terms_version": "2026-08-16-v1"},
        "cases": {
            CASE_ID: {
                "id": CASE_ID,
                "title": "Исковое заявление",
                "filename": "KORGAN_iskovoe_zayavlenie.docx",
                "document_base64": base64.b64encode(b"PK\x03\x04 korgan").decode("ascii"),
            }
        },
    }

    async def load(_user_id: str) -> dict[str, Any]:
        return state

    monkeypatch.setattr(core.legacy, "_state", load)


def _links(host: str, extra: dict[str, str] | None = None) -> dict[str, Any]:
    headers = {"X-Telegram-Init-Data": _init_data(), "Host": host}
    headers.update(extra or {})
    with TestClient(app) as client:
        response = client.post(f"/miniapp/cases/{CASE_ID}/document/access", headers=headers)
    assert response.status_code == 200
    return response.json()


def test_own_domain_link_is_https_without_proxy_header(ready_case: None) -> None:
    links = _links("api.korgan.kz")

    assert links["download_url"].startswith("https://api.korgan.kz/")
    assert links["preview_url"].startswith("https://api.korgan.kz/")


def test_railway_domain_link_stays_https(ready_case: None) -> None:
    links = _links("korgan-api-production.up.railway.app")

    assert links["download_url"].startswith("https://korgan-api-production.up.railway.app/")


def test_proxy_scheme_is_respected(ready_case: None) -> None:
    links = _links("api.korgan.kz", {"X-Forwarded-Proto": "https"})

    assert links["download_url"].startswith("https://api.korgan.kz/")


def test_local_development_keeps_plain_http(ready_case: None) -> None:
    # Локальная разработка идёт без сертификата, и подменять схему там не на что.
    links = _links("127.0.0.1:8000")

    assert links["download_url"].startswith("http://127.0.0.1:8000/")


def test_external_host_can_include_a_numeric_port(ready_case: None) -> None:
    links = _links("api.korgan.kz:8443")

    assert links["download_url"].startswith("https://api.korgan.kz:8443/")


def test_local_ipv6_host_keeps_plain_http(ready_case: None) -> None:
    links = _links("[::1]:8000")

    assert links["download_url"].startswith("http://[::1]:8000/")
