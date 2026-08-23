from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from korgan.legal_types import ExtractedDocument
from korgan.request_race_guard import _upload_followup
from korgan.request_scope import start_new_document_request
from korgan.upload_followup_guard import (
    _OLD_FOLLOWUP_KK,
    _PRETRIAL_RESPONSE_FOLLOWUP_KK,
    _UploadMessageProxy,
)


class _Bot:
    async def send_chat_action(self, *_args: object, **_kwargs: object) -> None:
        return None


class _Message:
    def __init__(self) -> None:
        self.answers: list[str] = []
        self.bot = _Bot()
        self.chat = SimpleNamespace(id=100)

    async def answer(self, text: str, *_args: object, **_kwargs: object) -> None:
        self.answers.append(str(text))


class _Service:
    async def extract_document(self, _data: bytes, filename: str, _mime_type: str | None) -> ExtractedDocument:
        return ExtractedDocument(
            filename=filename,
            document_type="Претензия о возврате предоплаты",
            text_summary="Тестовый документ.",
        )


async def _state(kind: str, language: str = "ru") -> tuple[MemoryStorage, FSMContext]:
    storage = MemoryStorage()
    state = FSMContext(
        storage=storage,
        key=StorageKey(bot_id=1, chat_id=100, user_id=200),
    )
    await state.set_data(
        {
            "request_id": "request-1",
            "request_kind": kind,
            "language": language,
            "documents": [],
            "facts": [],
        }
    )
    return storage, state


def test_pretrial_response_upload_followup_has_no_claim_reference_ru() -> None:
    text = _upload_followup("pretrial_response", "ru")
    assert "ответа на претензию" in text.lower()
    assert "подготовить иск" not in text.lower()


def test_pretrial_response_upload_followup_has_no_claim_reference_kk() -> None:
    text = _upload_followup("pretrial_response", "kk")
    assert "сотқа дейінгі талапқа жауап" in text.lower()
    assert "талап қою арыз" not in text.lower()


def test_claim_upload_followup_remains_unchanged() -> None:
    text = _upload_followup("claim", "ru")
    assert "подготовить иск" in text.lower()
    assert "word (.docx)" in text.lower()


def test_unknown_upload_followup_is_document_neutral() -> None:
    text = _upload_followup("", "ru")
    assert "выбранным документом" in text.lower()
    assert "подготовить иск" not in text.lower()


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


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        ("claim", "попросить подготовить иск"),
        ("pretrial", "подготовку досудебной претензии"),
        ("pretrial_response", "подготовку ответа на претензию"),
        ("response", "подготовку отзыва на иск"),
        ("contract", "подготовку договора"),
    ],
)
def test_installed_upload_handler_uses_active_request_kind(
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    expected: str,
) -> None:
    async def scenario() -> None:
        import korgan.strict_bot  # noqa: F401
        from korgan import bot as base_bot

        storage, state = await _state(kind)
        message = _Message()
        monkeypatch.setattr(base_bot, "service", _Service())

        async def save_document(current_state: FSMContext, extracted: ExtractedDocument) -> int:
            data = await current_state.get_data()
            documents = list(data.get("documents", []) or [])
            documents.append(extracted.as_context())
            await current_state.update_data(documents=documents)
            return len(documents)

        monkeypatch.setattr(base_bot, "_save_document", save_document)
        try:
            await base_bot._analyze_upload(message, state, b"pdf", "claim.pdf", "application/pdf")
            assert len(message.answers) == 1
            text = message.answers[0].lower()
            assert expected in text
            if kind != "claim":
                assert "попросить подготовить иск" not in text
        finally:
            await storage.close()

    asyncio.run(scenario())


def test_installed_upload_handler_suppresses_notice_when_request_switches_during_save(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        import korgan.strict_bot  # noqa: F401
        from korgan import bot as base_bot

        storage, state = await _state("pretrial_response")
        message = _Message()
        monkeypatch.setattr(base_bot, "service", _Service())
        save_started = asyncio.Event()
        release_save = asyncio.Event()

        async def slow_save(current_state: FSMContext, extracted: ExtractedDocument) -> int:
            data = await current_state.get_data()
            documents = list(data.get("documents", []) or [])
            documents.append(extracted.as_context())
            await current_state.update_data(documents=documents)
            save_started.set()
            await release_save.wait()
            return len(documents)

        monkeypatch.setattr(base_bot, "_save_document", slow_save)
        try:
            upload_task = asyncio.create_task(
                base_bot._analyze_upload(message, state, b"pdf", "claim.pdf", "application/pdf")
            )
            await save_started.wait()
            switch_task = asyncio.create_task(
                start_new_document_request(state, kind="contract", mode="contract_details")
            )
            await asyncio.sleep(0)
            release_save.set()
            await upload_task
            await switch_task

            assert message.answers == []
            latest = await state.get_data()
            assert latest.get("request_kind") == "contract"
            assert latest.get("documents") == []
        finally:
            await storage.close()

    asyncio.run(scenario())


def test_strict_bot_installs_contextual_handlers_on_actual_upload_paths() -> None:
    import korgan.strict_bot  # noqa: F401
    from korgan import bot as base_bot
    from korgan import kazakh_ui

    assert base_bot._analyze_upload.__module__ == "korgan.request_race_guard"
    assert "_upload_followup" in inspect.getsource(base_bot._analyze_upload)
    assert kazakh_ui._analyze_upload_kk.__module__ == "korgan.upload_followup_guard"
    assert "pretrial_response" in inspect.getsource(kazakh_ui._analyze_upload_kk)
