from __future__ import annotations

from types import SimpleNamespace

from korgan_legal_ai.domain.exceptions import ClarificationRequired
from korgan_legal_ai.domain.models import ReadinessStatus
from korgan_legal_ai.telegram.client import split_text
from korgan_legal_ai.telegram.runtime import TelegramRuntime
from korgan_legal_ai.telegram.session import InMemorySessionStore, SessionState


class FakeAPI:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str, dict | None]] = []
        self.answered: list[str] = []

    def send_message(self, chat_id: int, value: str, *, reply_markup=None) -> None:
        self.sent.append((chat_id, value, reply_markup))

    def answer_callback_query(self, callback_query_id: str) -> None:
        self.answered.append(callback_query_id)


class FakeEngine:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def process(self, raw_text: str):
        self.calls.append(raw_text)
        return SimpleNamespace(
            document=SimpleNamespace(
                readiness=ReadinessStatus.READY_FOR_FINAL_HUMAN_REVIEW,
                needs_verification=[],
                text="ИСК\nИстец: ТОО A\nОтветчик: ТОО B",
            )
        )


class ClarifyingEngine(FakeEngine):
    def process(self, raw_text: str):
        self.calls.append(raw_text)
        if len(self.calls) == 1:
            raise ClarificationRequired(["Укажите точную дату исполнения обязательства"])
        return SimpleNamespace(
            document=SimpleNamespace(
                readiness=ReadinessStatus.LAWYER_REVIEW_DRAFT,
                needs_verification=["limitation"],
                text="ИСК\nИстец: ТОО A\nОтветчик: ТОО B",
            )
        )


def message(text: str, *, user_id: int = 10, chat_id: int = 10, chat_type: str = "private"):
    return {
        "update_id": 1,
        "message": {
            "from": {"id": user_id},
            "chat": {"id": chat_id, "type": chat_type},
            "text": text,
        },
    }


def callback(data: str, *, user_id: int = 10, chat_id: int = 10):
    return {
        "update_id": 2,
        "callback_query": {
            "id": "cb-1",
            "from": {"id": user_id},
            "message": {"chat": {"id": chat_id, "type": "private"}},
            "data": data,
        },
    }


def consent_and_start_claim(runtime: TelegramRuntime) -> None:
    runtime.handle_update(message("/start"))
    runtime.handle_update(callback("lang:ru"))
    runtime.handle_update(callback("consent:accept"))
    runtime.handle_update(callback("flow:claim"))


def test_claim_flow_requires_consent_and_releases_only_engine_result() -> None:
    api = FakeAPI()
    engine = FakeEngine()
    store = InMemorySessionStore()
    runtime = TelegramRuntime(api=api, engine=engine, sessions=store)

    consent_and_start_claim(runtime)
    runtime.handle_update(message("ТОО A оказало услуги ТОО B. Долг 1000000 тенге."))

    assert engine.calls == ["ТОО A оказало услуги ТОО B. Долг 1000000 тенге."]
    assert any("READY FOR FINAL HUMAN REVIEW" in value for _, value, _ in api.sent)
    assert any(value.startswith("ИСК") for _, value, _ in api.sent)
    session = store.get(10)
    assert session.case_buffer is None
    assert session.state == SessionState.MENU


def test_clarification_keeps_case_only_until_followup_then_clears_it() -> None:
    api = FakeAPI()
    engine = ClarifyingEngine()
    store = InMemorySessionStore()
    runtime = TelegramRuntime(api=api, engine=engine, sessions=store)

    consent_and_start_claim(runtime)
    runtime.handle_update(message("Долг по договору 1000000 тенге."))
    session = store.get(10)
    assert session.state == SessionState.AWAITING_CLARIFICATION
    assert session.case_buffer == "Долг по договору 1000000 тенге."

    runtime.handle_update(message("Срок оплаты был 01.08.2026."))
    assert "Дополнение пользователя" in engine.calls[-1]
    assert store.get(10).case_buffer is None


def test_private_chat_boundary_prevents_group_case_processing() -> None:
    api = FakeAPI()
    engine = FakeEngine()
    runtime = TelegramRuntime(api=api, engine=engine)

    runtime.handle_update(message("секретное дело", chat_type="group"))

    assert engine.calls == []
    assert any("личном чате" in value for _, value, _ in api.sent)


def test_claim_button_without_consent_does_not_call_engine() -> None:
    api = FakeAPI()
    engine = FakeEngine()
    runtime = TelegramRuntime(api=api, engine=engine)

    runtime.handle_update(callback("flow:claim"))

    assert engine.calls == []
    assert any("Сначала необходимо" in value for _, value, _ in api.sent)


def test_split_text_respects_safe_telegram_limit() -> None:
    chunks = split_text(("слово " * 1500).strip(), limit=3900)
    assert len(chunks) > 1
    assert all(0 < len(chunk) <= 3900 for chunk in chunks)
    assert "".join(chunks).replace(" ", "") == ("слово" * 1500)
