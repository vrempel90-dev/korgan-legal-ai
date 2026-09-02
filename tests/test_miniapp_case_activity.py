from __future__ import annotations

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
