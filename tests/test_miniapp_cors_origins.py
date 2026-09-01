"""Браузер пускают туда, откуда Mini App действительно открывается.

Адрес Mini App объявляет сам сервис: `MINIAPP_PUBLIC_URL` — это и кнопка,
которую бот регистрирует в Telegram, и origin страницы, открытой в WebView.
Список разрешённых CORS-origin при этом был закрытым перечнем из трёх адресов,
и связи между ними не было никакой.

Расходятся они молча и полностью. Кнопка ведёт на объявленный адрес, страница
открывается, а первый же запрос к API получает preflight 400 «Disallowed CORS
origin»: браузер обрывает запрос до отправки, до сервера ничего не доходит,
в логах пусто. Пользователь видит «Не удалось подключиться» на всех вкладках
сразу — и так до тех пор, пока адрес не впишут в список руками.

Поэтому объявленный адрес разрешён по построению, а не по совпадению.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from korgan import miniapp_api_recovery_cors as cors

BASELINE = "https://korgan-miniapp-staging-production.up.railway.app"


def test_published_miniapp_origin_is_allowed():
    origins = cors.allowed_origins("https://korgan-live.example.org")

    assert "https://korgan-live.example.org" in origins


def test_published_origin_drops_path_and_query():
    origins = cors.allowed_origins("https://korgan-live.example.org/app/?start=1")

    assert "https://korgan-live.example.org" in origins
    assert not any(origin.endswith("/app/") for origin in origins)


def test_known_origins_survive_the_published_one():
    origins = cors.allowed_origins("https://korgan-live.example.org")

    assert BASELINE in origins
    assert "https://korgan-miniapp-web-recovery-1600-production.up.railway.app" in origins
    assert "https://korgan-miniapp-live-clean-production.up.railway.app" in origins


def test_published_origin_is_not_listed_twice():
    origins = cors.allowed_origins(BASELINE + "/")

    assert origins.count(BASELINE) == 1


def test_unset_or_unusable_public_url_changes_nothing():
    baseline = cors.allowed_origins("")

    assert baseline == cors.allowed_origins("   ")
    assert baseline == cors.allowed_origins("http://korgan-live.example.org")
    assert baseline == cors.allowed_origins("korgan-live.example.org")
    assert baseline == cors.allowed_origins("https://")


def test_preflight_from_known_origin_passes():
    with TestClient(cors.app) as client:
        response = client.options(
            "/miniapp/cases",
            headers={
                "Origin": BASELINE,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "x-telegram-init-data",
            },
        )

    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == BASELINE


def test_preflight_from_foreign_origin_is_refused():
    with TestClient(cors.app) as client:
        response = client.options(
            "/miniapp/cases",
            headers={
                "Origin": "https://not-korgan.example.com",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers
