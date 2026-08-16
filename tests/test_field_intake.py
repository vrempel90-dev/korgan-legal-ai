"""The missing-field collection loop: the bug, and the guard against its return.

The loop: asked for «дата рождения истца», the user answered «03.03.1999», and
the bot asked again — because `claim_preflight` looks for a date *near the words*
«дата рождения», and an answer does not repeat the question.

These tests drive the real handlers over an aiogram MemoryStorage, so they cover
the order of operations too (parse → write → await → re-read → decide), not just
the parsing helpers.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from korgan import bot as korgan_bot
from korgan.claim_preflight import inspect_claim_context
from korgan.field_intake import detect_kind, normalize_answer, normalize_date, normalize_iin

_CASE = (
    "Я истец Иванов Иван Иванович, дал в долг 800 000 тенге Петрову Петру Петровичу "
    "(ответчик). Деньги в срок не возвращены."
)


@dataclass
class FakeMessage:
    """Minimal Message: records what the bot says back."""

    text: str
    sent: list[str] = field(default_factory=list)
    markups: list[object] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.chat = SimpleNamespace(id=1)
        self.from_user = SimpleNamespace(id=1, is_bot=False)
        self.bot = SimpleNamespace(send_chat_action=self._noop)

    async def _noop(self, *args, **kwargs) -> None:
        return None

    async def answer(self, text: str, **kwargs) -> None:
        self.sent.append(text)
        self.markups.append(kwargs.get("reply_markup"))


class Dialog:
    """Drives korgan.bot handlers over a real FSM storage."""

    def __init__(self) -> None:
        self.storage = MemoryStorage()
        self.state = FSMContext(
            storage=self.storage,
            key=StorageKey(bot_id=1, chat_id=1, user_id=1),
        )
        self.transcript: list[tuple[str, str]] = []

    async def start_case(self, case: str = _CASE) -> None:
        await self.state.set_data(
            {"language": "ru", "documents": [], "facts": [case], "consulted_articles": [], "mode": "main"}
        )

    async def say(self, text: str) -> list[str]:
        message = FakeMessage(text)
        self.transcript.append(("user", text))
        data = await self.state.get_data()
        if data.get("mode") == "claim_details":
            await korgan_bot._handle_missing_field_answer(message, self.state, data)
        else:
            await korgan_bot.claim_handler(message, self.state)
        for reply in message.sent:
            self.transcript.append(("bot", reply))
        return message.sent

    async def pending(self) -> list[str]:
        return list((await self.state.get_data()).get("pending_fields", []) or [])


@pytest.fixture(autouse=True)
def _service_present(monkeypatch: pytest.MonkeyPatch) -> None:
    """claim_handler returns early when no service is configured."""
    monkeypatch.setattr(korgan_bot, "service", object())


def run(coro):
    return asyncio.run(coro)


# --- parsing helpers -------------------------------------------------------


def test_date_formats_are_accepted_and_normalized() -> None:
    assert normalize_date("03.03.1999") == "03.03.1999"
    assert normalize_date("3/3/1999") == "03.03.1999"
    assert normalize_date("1999-03-03") == "03.03.1999"
    assert normalize_date("31.02.1999") is None  # not a real date
    assert normalize_date("вчера") is None


def test_iin_is_accepted_only_as_twelve_digits() -> None:
    assert normalize_iin("990303300123") == "990303300123"
    assert normalize_iin("9903 0330 0123") == "990303300123"
    assert normalize_iin("99030330012") is None


def test_bare_values_are_classified() -> None:
    assert detect_kind("03.03.1999") == "date"
    assert detect_kind("990303300123") == "iin"
    assert detect_kind("г. Алматы, ул. Абая, д. 15, кв. 3") == "address"
    assert detect_kind("Петров Пётр Петрович") == "name"


def test_bare_date_is_recorded_under_the_field_that_was_asked_for() -> None:
    intake = normalize_answer(["дата рождения истца", "ИИН истца"], "03.03.1999")
    assert intake.recorded == ["Дата рождения истца: 03.03.1999"]
    assert intake.matched == ["дата рождения истца"]
    assert not intake.errors


def test_recorded_answer_is_visible_to_the_preflight_check() -> None:
    """The heart of the bug: what we write must be what the check can read."""
    intake = normalize_answer(["дата рождения истца"], "03.03.1999")
    assert "дата рождения истца" not in inspect_claim_context(_CASE + "\n" + intake.as_case_text()).missing


def test_unparsable_value_returns_a_format_error_not_silence() -> None:
    intake = normalize_answer(["дата рождения истца"], "позавчера")
    assert not intake.progressed
    assert intake.errors
    assert "15.06.1990" in intake.errors[0]


def test_ambiguous_value_asks_the_user_to_label_it() -> None:
    intake = normalize_answer(
        ["ФИО истца полностью", "ФИО ответчика полностью"], "Петров Пётр Петрович"
    )
    assert not intake.progressed
    assert "подходит сразу к нескольким полям" in intake.errors[0]


def test_user_written_labels_are_kept_as_is() -> None:
    intake = normalize_answer(
        ["ИИН истца", "дата рождения истца"], "ИИН истца 990303300123"
    )
    assert intake.recorded == ["ИИН истца 990303300123"]


def test_multiline_answer_fills_several_fields_at_once() -> None:
    intake = normalize_answer(
        ["дата рождения истца", "ИИН истца", "адрес места жительства истца"],
        "03.03.1999\n990303300123\nг. Алматы, ул. Абая, д. 15, кв. 3",
    )
    assert len(intake.recorded) == 3
    assert not intake.errors


# --- the dialogue itself ---------------------------------------------------


def test_answering_the_date_no_longer_repeats_the_same_question() -> None:
    async def scenario() -> None:
        dialog = Dialog()
        await dialog.start_case()

        first = await dialog.say("подготовь иск")
        assert "дата рождения истца" in first[0]

        second = await dialog.say("03.03.1999")
        assert second, "бот промолчал"
        # The question moved on: the date is no longer being asked for.
        assert "дата рождения истца" not in second[-1]
        assert "дата рождения истца" not in await dialog.pending()

    run(scenario())


@pytest.mark.parametrize(
    ("answer", "field_label"),
    [
        ("03.03.1999", "дата рождения истца"),
        ("990303300123", "ИИН истца"),
        ("Адрес места жительства истца: г. Алматы, ул. Абая, д. 15, кв. 3", "адрес места жительства истца"),
    ],
)
def test_no_field_loops_on_a_direct_answer(answer: str, field_label: str) -> None:
    """Task 3: the defect was general, so the check is general too."""

    async def scenario() -> None:
        dialog = Dialog()
        await dialog.start_case()
        await dialog.say("подготовь иск")
        assert field_label in await dialog.pending()

        await dialog.say(answer)
        assert field_label not in await dialog.pending()

    run(scenario())


def test_bare_name_fills_the_defendant_field_when_only_it_is_outstanding() -> None:
    """A bare name is unambiguous once only one name field remains."""
    intake = normalize_answer(["ФИО ответчика полностью", "ИИН истца"], "Петров Пётр Петрович")
    assert intake.recorded == ["ФИО ответчика: Петров Пётр Петрович"]
    assert intake.matched == ["ФИО ответчика полностью"]

    case = "Мне не вернули долг. Ответчик уклоняется."
    assert "ФИО ответчика полностью" not in inspect_claim_context(
        case + "\n" + intake.as_case_text()
    ).missing


def test_value_matching_two_fields_asks_which_one_instead_of_looping() -> None:
    """Both addresses are outstanding, so a bare address is genuinely ambiguous."""

    async def scenario() -> None:
        dialog = Dialog()
        await dialog.start_case()
        prompt = (await dialog.say("подготовь иск"))[0]

        replies = await dialog.say("г. Алматы, ул. Абая, д. 15, кв. 3")
        assert replies
        assert replies[0] != prompt, "бот повторил тот же запрос"
        assert "подходит сразу к нескольким полям" in replies[0]

        # Labelling it resolves the ambiguity and the field is filled.
        await dialog.say("Адрес места жительства истца: г. Алматы, ул. Абая, д. 15, кв. 3")
        assert "адрес места жительства истца" not in await dialog.pending()

    run(scenario())


def test_every_field_can_be_filled_in_sequence_without_getting_stuck() -> None:
    async def scenario() -> None:
        dialog = Dialog()
        await dialog.start_case()
        await dialog.say("подготовь иск")

        answers = [
            "03.03.1999",
            "990303300123",
            "Адрес места жительства истца: г. Алматы, ул. Абая, д. 15, кв. 3",
            "Адрес места жительства ответчика: г. Астана, ул. Кенесары, д. 40, кв. 12",
        ]
        for answer in answers:
            before = await dialog.pending()
            await dialog.say(answer)
            after = await dialog.pending()
            assert after != before, f"поле не заполнилось: {answer!r} (осталось {after})"

        assert not await dialog.pending()

    run(scenario())


def test_unparsable_answer_gets_an_error_instead_of_the_same_prompt() -> None:
    async def scenario() -> None:
        dialog = Dialog()
        await dialog.start_case()
        await dialog.say("подготовь иск")

        replies = await dialog.say("не помню")
        assert replies
        assert "Не получилось распознать" in replies[0]
        assert "не хватает обязательных данных" not in replies[0]
        assert "Пример:" in replies[0]

    run(scenario())


def test_repeated_identical_prompt_triggers_the_escape_route() -> None:
    """Task 2: the loop guard fires even if a future defect breaks parsing."""

    async def scenario() -> None:
        dialog = Dialog()
        await dialog.start_case()
        await dialog.say("подготовь иск")

        # Answers that record something but never satisfy any field keep the
        # missing set identical — exactly the shape of the original loop.
        last: list[str] = []
        for _ in range(3):
            last = await dialog.say("уточню позже")

        assert "начать дело заново" in last[-1].lower()
        assert "передать его юристу-человеку" in last[-1].lower()
        data = await dialog.state.get_data()
        assert data["intake_failures"] >= 2

    run(scenario())
