"""Каждый HTTP-маршрут MiniApp обслуживается ровно одним, ожидаемым слоём.

Приложение собирается из восьми слоёв поверх одного объекта FastAPI. Дубликат
маршрута означал бы, что запрос молча уходит не в тот обработчик: например
генерация документа мимо платёжного шлюза или приём чека мимо ручного
подтверждения администратором.
"""

from __future__ import annotations

import pytest

from tests.production_routes import EXPECTED_OWNERS, all_routes, endpoint, owner


@pytest.mark.parametrize(("path", "method", "expected"), [
    (path, method, expected) for (path, method), expected in sorted(EXPECTED_OWNERS.items())
])
def test_route_is_owned_by_the_expected_layer(path: str, method: str, expected: str) -> None:
    assert owner(path, method) == expected


def test_no_miniapp_route_is_registered_twice() -> None:
    """`_drop_route` обязан снимать перекрытый маршрут, а не оставлять дубль."""
    seen: dict[tuple[str, str], int] = {}
    for route in all_routes():
        path = getattr(route, "path", None)
        if not path or not (path.startswith("/miniapp") or path == "/health"):
            continue
        for method in getattr(route, "methods", set()) or set():
            key = (path, method)
            seen[key] = seen.get(key, 0) + 1

    duplicates = {key: count for key, count in seen.items() if count > 1}
    assert duplicates == {}


def test_document_generation_cannot_bypass_payment_or_persisted_jobs() -> None:
    """Прямая генерация v2/v5 не должна обходить платёж и очередь задач."""
    from korgan import miniapp_api_v2, miniapp_api_v5, miniapp_generation_api

    handler = endpoint("/miniapp/documents/generate", "POST")
    assert handler is miniapp_generation_api.generate_document_job
    assert handler is not miniapp_api_v5.generate_document
    assert handler is not miniapp_api_v2.generate_document
