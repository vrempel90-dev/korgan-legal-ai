from __future__ import annotations

import asyncio
import inspect

from korgan.request_race_guard import _upload_followup
from korgan.upload_followup_guard import (
    _OLD_FOLLOWUP_KK,
    _PRETRIAL_RESPONSE_FOLLOWUP_KK,
    _UploadMessageProxy,
)


class _Message:
    def __init__(self) -> None:
        self.answers: list[str] = []

    async def answer(self, text: str, *_args: object, **_kwargs: object) -> None:
        self.answers.append(str(text))


def test_pretrial_response_upload_followup_has_no_claim_reference_ru() -> None:
    text = _upload_followup("pretrial_response", "ru")
    assert "ответа на претензию" in text.lower()
    assert "иск" not in text.lower()


def test_pretrial_response_upload_followup_has_no_claim_reference_kk() -> None:
    text = _upload_followup("pretrial_response", "kk")
    assert "сотқа дейінгі талапқа жауап" in text.lower()
    assert "талап қою арыз" not in text.lower()


def test_claim_upload_followup_remains_unchanged() -> None:
    text = _upload_followup("claim", "ru")
    assert "подготовить иск" in text.lower()
    assert "word (.docx)" in text.lower()


def test_kazakh_pretrial_response_proxy_replaces_claim_cta_only() -> None:
    async def scenario() -> None:
        message = _Message()
        proxy = _UploadMessageProxy(
            message,
            old_followup=_OLD_FOLLOWUP_KK,
            new_followup=_PRETRIAL_RESPONSE_FOLLOWUP_KK,
        )
        await proxy.answer(f"Материал.\n\n{_OLD_FOLLOWUP_KK}")
        assert len(message.answers) == 1
        assert "сотқа дейінгі талапқа жауап" in message.answers[0].lower()
        assert "талап қою арыз" not in message.answers[0].lower()

    asyncio.run(scenario())


def test_strict_bot_installs_contextual_handlers_on_actual_upload_paths() -> None:
    import korgan.strict_bot  # noqa: F401
    from korgan import bot as base_bot
    from korgan import kazakh_ui

    assert base_bot._analyze_upload.__module__ == "korgan.request_race_guard"
    assert "_upload_followup" in inspect.getsource(base_bot._analyze_upload)
    assert kazakh_ui._analyze_upload_kk.__module__ == "korgan.upload_followup_guard"
    assert "pretrial_response" in inspect.getsource(kazakh_ui._analyze_upload_kk)
