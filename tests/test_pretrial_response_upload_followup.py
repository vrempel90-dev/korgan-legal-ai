from __future__ import annotations

import inspect

from korgan.request_race_guard import _upload_followup


def test_pretrial_response_upload_followup_has_no_claim_reference_ru() -> None:
    text = _upload_followup("pretrial_response", "ru")
    assert "ответа на претензию" in text.lower()
    assert "иск" not in text.lower()


def test_pretrial_response_upload_followup_has_no_claim_reference_kk() -> None:
    text = _upload_followup("pretrial_response", "kk")
    assert "сотқа дейінгі талапқа жауап" in text.lower()
    assert "иск" not in text.lower()


def test_claim_upload_followup_remains_unchanged() -> None:
    text = _upload_followup("claim", "ru")
    assert "подготовить иск" in text.lower()
    assert "word (.docx)" in text.lower()


def test_strict_bot_installs_race_guard_with_contextual_followup() -> None:
    import korgan.strict_bot  # noqa: F401
    from korgan import bot as base_bot

    assert base_bot._analyze_upload.__module__ == "korgan.request_race_guard"
    assert "_upload_followup" in inspect.getsource(base_bot._analyze_upload)
