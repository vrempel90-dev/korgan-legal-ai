"""Единый владелец запуска и остановки ASGI-приложения.

``@app.on_event`` объявлен устаревшим и будет удалён из FastAPI. Но снятие с
поддержки — не единственная причина уйти от него. Слои Mini App (v2, v3, v4)
регистрируют обработчики на одном и том же объекте приложения, поэтому порядок
открытия и закрытия хранилищ определялся порядком импортов, а падение на старте
оставляло уже открытые хранилища незакрытыми.

Здесь порядок явный: старты выполняются в порядке регистрации, остановки — в
том же порядке, и остановка выполняется всегда, включая падение старта или
работы приложения. Свёртываются только те слои, которые успели подняться.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

Handler = Callable[[], Awaitable[None]]

_REGISTRY_ATTR = "_korgan_lifespan_registry"


@dataclass(slots=True)
class _Registry:
    """Слои жизненного цикла одного приложения в порядке регистрации."""

    layers: list[tuple[Handler | None, Handler | None]] = field(default_factory=list)


def _registry(app: Any) -> _Registry:
    registry = getattr(app, _REGISTRY_ATTR, None)
    if registry is not None:
        return registry

    registry = _Registry()
    setattr(app, _REGISTRY_ATTR, registry)
    previous = app.router.lifespan_context

    @contextlib.asynccontextmanager
    async def _lifespan(scope_app: Any) -> AsyncIterator[None]:
        started: list[Handler] = []
        try:
            for startup, shutdown in list(registry.layers):
                if startup is not None:
                    await startup()
                if shutdown is not None:
                    started.append(shutdown)
            async with previous(scope_app):
                yield
        finally:
            for shutdown in started:
                await shutdown()

    app.router.lifespan_context = _lifespan
    return registry


def add_lifespan(
    app: Any,
    *,
    startup: Handler | None = None,
    shutdown: Handler | None = None,
) -> None:
    """Добавить слой запуска/остановки поверх уже собранного приложения."""
    _registry(app).layers.append((startup, shutdown))
