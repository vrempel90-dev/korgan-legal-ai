from __future__ import annotations

from korgan import miniapp_telegram_delivery as telegram_delivery
from korgan.miniapp_api_recovery_cors import app


def _route(path: str, method: str):
    wanted = method.upper()
    matches = [
        route
        for route in app.routes
        if getattr(route, "path", None) == path
        and wanted in (getattr(route, "methods", set()) or set())
    ]
    assert len(matches) == 1, f"Expected one {method} route for {path}, got {len(matches)}"
    return matches[0]


def test_ready_document_has_reliable_telegram_delivery_route() -> None:
    route = _route("/miniapp/cases/{case_id}/document/telegram", "POST")
    assert route.endpoint is telegram_delivery.send_document_to_telegram
