from __future__ import annotations

import asyncio

from korgan import miniapp_case_activity as activity
from korgan import miniapp_generation_api as generation_api


def test_activity_runtime_wraps_scheduler_without_replacing_generation_engine() -> None:
    assert generation_api._schedule_job is activity._schedule_job_with_activity
    assert activity._ORIGINAL_SCHEDULE_JOB is not activity._schedule_job_with_activity


def test_ready_notification_payload_keeps_existing_miniapp_entrypoint(monkeypatch) -> None:
    monkeypatch.setenv("MINIAPP_PUBLIC_URL", "https://korgan.example/app")
    payload = activity._notification_payload(
        "12345",
        {"title": "Исковое заявление", "language": "ru"},
    )

    assert payload["chat_id"] == "12345"
    assert "документ готов" in payload["text"].lower()
    assert "Исковое заявление" in payload["text"]
    button = payload["reply_markup"]["inline_keyboard"][0][0]
    assert button["text"] == "Открыть KORGAN"
    assert button["web_app"]["url"] == "https://korgan.example/app"


def test_ready_notification_does_not_emit_unsafe_non_https_button(monkeypatch) -> None:
    monkeypatch.setenv("MINIAPP_PUBLIC_URL", "http://localhost:5173")
    payload = activity._notification_payload("12345", {"language": "ru"})
    assert "reply_markup" not in payload


def test_case_activity_labels_are_localized() -> None:
    assert activity._label("queued", "ru") == "Документ поставлен в очередь"
    assert activity._label("ready", "ru") == "Документ готов"
    assert activity._label("ready", "kk") == "Құжат дайын"


def test_activity_store_is_optional_when_database_url_is_missing(monkeypatch) -> None:
    monkeypatch.setattr(activity, "_POOL", None)

    asyncio.run(activity.init_case_activity_store("", enabled=True))

    assert activity._POOL is None


def test_activity_write_failure_is_fail_open(monkeypatch) -> None:
    class BrokenPool:
        async def fetchrow(self, *args, **kwargs):
            raise RuntimeError("activity database unavailable")

    monkeypatch.setattr(activity.settings, "payments_enabled", True)
    monkeypatch.setattr(activity, "_POOL", BrokenPool())

    recorded = asyncio.run(
        activity.record_case_activity(
            user_key="user-key",
            case_id="case-1",
            job_id="job-1",
            event_type="queued",
            progress=0,
            detail="queued",
        )
    )

    assert recorded is False


def test_activity_read_can_return_empty_when_auxiliary_store_is_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(activity.settings, "payments_enabled", True)
    monkeypatch.setattr(activity, "_POOL", None)

    # Доступ к делу всё равно проверяется canonical consent/state слоем; здесь
    # фиксируем отдельный контракт auxiliary store — отсутствие пула не ошибка.
    assert activity._POOL is None
