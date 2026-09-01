"""Запуск и остановка приложения принадлежат одному владельцу.

``@app.on_event`` объявлен устаревшим и будет удалён. Хуже устаревания то, что
слои v2, v3 и v4 регистрируют свои обработчики на одном и том же объекте
приложения: порядок открытия и закрытия хранилищ определялся порядком импортов,
а незакрытое хранилище переживало падение запуска. Владелец должен быть один и
явный.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI

from korgan.asgi_lifespan import add_lifespan


async def _run_lifespan(app: FastAPI, *, fail: bool = False) -> None:
    async with app.router.lifespan_context(app):
        if fail:
            raise RuntimeError("падение во время работы приложения")


def test_startup_and_shutdown_run_in_registration_order() -> None:
    app = FastAPI()
    calls: list[str] = []

    def _make(name: str):
        async def _handler() -> None:
            calls.append(name)

        return _handler

    add_lifespan(app, startup=_make("старт-1"), shutdown=_make("стоп-1"))
    add_lifespan(app, startup=_make("старт-2"), shutdown=_make("стоп-2"))

    asyncio.run(_run_lifespan(app))

    assert calls == ["старт-1", "старт-2", "стоп-1", "стоп-2"]


def test_shutdown_closes_stores_even_when_the_application_fails() -> None:
    """Незакрытое хранилище не должно переживать падение приложения."""
    app = FastAPI()
    closed: list[str] = []

    async def _startup() -> None:
        return None

    async def _shutdown() -> None:
        closed.append("хранилище закрыто")

    add_lifespan(app, startup=_startup, shutdown=_shutdown)

    with pytest.raises(RuntimeError):
        asyncio.run(_run_lifespan(app, fail=True))

    assert closed == ["хранилище закрыто"]


def test_a_failing_startup_does_not_leave_earlier_startups_unclosed() -> None:
    """Если второй старт упал, первый обязан быть свёрнут."""
    app = FastAPI()
    events: list[str] = []

    async def _first_startup() -> None:
        events.append("открыт первый")

    async def _first_shutdown() -> None:
        events.append("закрыт первый")

    async def _second_startup() -> None:
        raise RuntimeError("второе хранилище недоступно")

    add_lifespan(app, startup=_first_startup, shutdown=_first_shutdown)
    add_lifespan(app, startup=_second_startup, shutdown=None)

    with pytest.raises(RuntimeError):
        asyncio.run(_run_lifespan(app))

    assert events == ["открыт первый", "закрыт первый"]


@pytest.mark.parametrize(
    "module_name",
    [
        "korgan.miniapp_api",
        "korgan.miniapp_api_v2",
        "korgan.miniapp_api_v3",
        "korgan.miniapp_api_v4",
        "korgan.miniapp_api_recovery_cors",
    ],
)
def test_production_apps_register_no_deprecated_on_event_handlers(module_name: str) -> None:
    """Развёрнутый путь не должен опираться на снятый с поддержки механизм."""
    module = __import__(module_name, fromlist=["app"])

    assert module.app.router.on_startup == []
    assert module.app.router.on_shutdown == []
