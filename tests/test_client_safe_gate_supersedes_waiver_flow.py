"""Боевой контракт шлюза проверки: клиент никогда не решает судьбу статьи.

В ``korgan/bot.py`` есть диалоговый шлюз, который на непройденной проверке
перечисляет клиенту дефекты правовых ссылок и предлагает ответить, что с ними
сделать: пометить статью NEEDS_VERIFICATION, убрать её, прислать недостающие
поля. ``client_safe_ui.install_client_safe_runtime()`` намеренно заменяет этот
шлюз: решение о норме принимает KORGAN или юрист, а не клиент.

До этого набора боевое поведение не было закреплено нигде. Проверялась только
заменённая реализация bot.py, и результат зависел от того, импортировал ли
какой-нибудь другой тестовый модуль ``korgan.strict_bot`` раньше по алфавиту.
Здесь фиксируется именно то, что работает на Railway.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from korgan import bot as korgan_bot
from korgan import client_safe_ui
from korgan.client_safe_ui import install_client_safe_runtime, sanitize_client_text


class _State:
    def __init__(self, data: dict[str, Any] | None = None) -> None:
        self.data = dict(data or {})

    async def get_data(self) -> dict[str, Any]:
        return dict(self.data)

    async def update_data(self, **kwargs: Any) -> None:
        self.data.update(kwargs)


class _Message:
    def __init__(self, text: str = "") -> None:
        self.text = text
        self.sent: list[str] = []
        self.from_user = None

    async def answer(self, text: str, **_: Any) -> None:
        self.sent.append(text)


class _Report:
    blocking = [
        "статья 616 ГК РК: текста нормы нет в проверенном корпусе KORGAN — содержание не подтверждено",
    ]


@pytest.fixture(autouse=True)
def installed() -> None:
    install_client_safe_runtime()


def test_client_safe_layer_owns_the_verification_gate() -> None:
    assert korgan_bot._enter_verification_gate is not client_safe_ui._original_enter_verification_gate
    assert korgan_bot._handle_verification_gate_reply is not client_safe_ui._original_handle_verification_gate_reply


def test_blocked_document_never_asks_the_client_to_waive_a_provision() -> None:
    message = _Message()
    state = _State({"mode": "claim_details", "claim_draft": {"any": True}})

    asyncio.run(korgan_bot._enter_verification_gate(message, state, object(), _Report()))

    assert message.sent == [client_safe_ui._GENERIC_CHECK_MESSAGE]
    body = " ".join(message.sent)
    for forbidden in ("616", "NEEDS_VERIFICATION", "корпус", "пометь", "убери"):
        assert forbidden not in body
    # Клиент не остаётся в состоянии, где от него ждут решения о норме.
    assert state.data["mode"] == "main"
    assert state.data["gate_issues"] == []
    assert state.data["claim_draft"] is None


def test_reply_on_a_stale_gate_returns_the_client_to_the_menu() -> None:
    message = _Message("пометь статью 616 ГК РК как NEEDS_VERIFICATION и продолжи")
    state = _State({"mode": "verification_gate", "gate_issues": ["что-то"], "claim_draft": {"any": True}})

    asyncio.run(korgan_bot._handle_verification_gate_reply(message, state, dict(state.data)))

    assert message.sent == [client_safe_ui._GENERIC_CHECK_MESSAGE]
    assert state.data["mode"] == "main"
    assert state.data["gate_issues"] == []
    assert state.data["claim_draft"] is None


@pytest.mark.parametrize(
    "internal_text",
    [
        "Как поступить: пометить статью 616 ГК РК как NEEDS_VERIFICATION?",
        "В замечаниях не было статьи 999 ГК РК. Уточните, что сделать с ними.",
        "Не понял, что сделать с замечаниями. Что именно нужно нужно сделать?",
        "Договор не выпущен: обнаружены дефекты правовых ссылок.",
    ],
)
def test_internal_verification_dialogue_never_reaches_the_client(internal_text: str) -> None:
    assert sanitize_client_text(internal_text) == client_safe_ui._GENERIC_CHECK_MESSAGE


def test_ordinary_legal_explanation_still_reaches_the_client() -> None:
    """Слой скрывает механику проверки, а не право. Обычный ответ не трогается."""
    text = "По статье 616 ГК РК заказчик обязан оплатить принятые работы."
    assert sanitize_client_text(text) == text
