"""Внешний адрес документа формируется только из безопасного хоста.

`X-Forwarded-Host` — недоверенный HTTP-заголовок. Если вернуть его как есть,
атакующий может выдать авторизованному пользователю подписанную ссылку на чужой
домен; клиент затем откроет её как ссылку KORGAN. Порт допустим, путь, пробелы и
управляющие символы — нет.
"""

from __future__ import annotations

import pytest
from starlette.requests import Request

from korgan import miniapp_document_access as access


def _request(host: str) -> Request:
    headers = [(b"host", b"internal:8000"), (b"x-forwarded-host", host.encode("ascii"))]
    return Request(
        {
            "type": "http",
            "scheme": "http",
            "server": ("internal", 8000),
            "path": "/",
            "query_string": b"",
            "headers": headers,
        }
    )


@pytest.mark.parametrize(
    "host",
    [
        "api.korgan.kz/evil.example",
        "api.korgan.kz @evil.example",
        "api.korgan.kz\\@evil.example",
        "api.korgan.kz:443:444",
        "api.korgan.kz:not-a-port",
        "[2001:db8::1]evil.example",
    ],
)
def test_external_base_rejects_host_header_injection(host: str) -> None:
    with pytest.raises(ValueError):
        access._external_base(_request(host))
