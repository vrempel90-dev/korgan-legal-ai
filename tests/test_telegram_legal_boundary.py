"""Telegram stays a transport layer.

The bot must not decide law on its own, must not bypass
Fact Lock -> Task Router -> Legal RAG -> Procedural Checks -> Drafting -> Final Legal QA,
and must not keep client session data in the canonical legal corpus.
"""
from __future__ import annotations

import re
from pathlib import Path
from threading import Event
from types import SimpleNamespace

from korgan_legal_ai.domain.exceptions import LegalQABlocked
from korgan_legal_ai.domain.models import ReadinessStatus
from korgan_legal_ai.telegram.runtime import TelegramRuntime
from korgan_legal_ai.telegram.session import InMemorySessionStore, SessionState

TELEGRAM_PACKAGE = Path(__file__).resolve().parents[1] / "src" / "korgan_legal_ai" / "telegram"

# Legal reasoning belongs to the engine; none of it may be hard-coded in the transport.
FORBIDDEN_LEGAL_PATTERNS = (
    r"\bГПК\b",
    r"\bГК\s+РК\b",
    r"\bст\.\s*\d",
    r"\bстатья\s+\d",
    r"\bМРП\b",
    r"госпошлин",
    r"подсудност",
    r"исковой давности",
    r"\d+\s*%",
)

# Modules the transport must not reach into directly: doing so would let Telegram answer a legal
# question without passing through the orchestrated pipeline.
FORBIDDEN_IMPORTS = (
    "korgan_legal_ai.corpus",
    "korgan_legal_ai.procedural",
    "korgan_legal_ai.procedural_rules",
    "korgan_legal_ai.research",
    "korgan_legal_ai.drafting",
    "korgan_legal_ai.qa",
    "korgan_legal_ai.calculations",
    "korgan_legal_ai.fact_lock",
    "korgan_legal_ai.router",
    "korgan_legal_ai.evidence",
)


class FakeAPI:
    def __init__(self) -> None:
        self.sent: list[str] = []

    def send_message(self, chat_id: int, value: str, *, reply_markup=None) -> None:
        self.sent.append(value)

    def answer_callback_query(self, callback_query_id: str) -> None:
        return None


def _message(value: str) -> dict:
    return {
        "update_id": 1,
        "message": {
            "from": {"id": 7},
            "chat": {"id": 7, "type": "private"},
            "text": value,
        },
    }


def _callback(data: str) -> dict:
    return {
        "update_id": 2,
        "callback_query": {
            "id": "cb",
            "from": {"id": 7},
            "message": {"chat": {"id": 7, "type": "private"}},
            "data": data,
        },
    }


def _consented_runtime(engine) -> tuple[TelegramRuntime, FakeAPI, InMemorySessionStore]:
    api = FakeAPI()
    store = InMemorySessionStore()
    runtime = TelegramRuntime(api=api, engine=engine, sessions=store)
    runtime.handle_update(_message("/start"))
    runtime.handle_update(_callback("lang:ru"))
    runtime.handle_update(_callback("consent:accept"))
    runtime.handle_update(_callback("flow:claim"))
    return runtime, api, store


def test_transport_contains_no_hard_coded_legal_norms() -> None:
    offenders: list[str] = []
    for path in sorted(TELEGRAM_PACKAGE.glob("*.py")):
        content = path.read_text(encoding="utf-8")
        for pattern in FORBIDDEN_LEGAL_PATTERNS:
            if re.search(pattern, content, flags=re.IGNORECASE):
                offenders.append(f"{path.name}: {pattern}")
    assert offenders == []


def test_transport_does_not_import_legal_layers_directly() -> None:
    offenders: list[str] = []
    for path in sorted(TELEGRAM_PACKAGE.glob("*.py")):
        content = path.read_text(encoding="utf-8")
        for module in FORBIDDEN_IMPORTS:
            if re.search(rf"^\s*(from|import)\s+{re.escape(module)}\b", content, flags=re.M):
                offenders.append(f"{path.name} -> {module}")
    assert offenders == []


def test_session_storage_touches_only_its_own_table() -> None:
    source = (TELEGRAM_PACKAGE / "postgres_session.py").read_text(encoding="utf-8")
    tables = set(re.findall(r"(?:FROM|INTO|UPDATE|JOIN)\s+([a-z_][a-z0-9_]*)", source))
    # Client session data and the canonical legal corpus never share storage.
    assert tables == {"telegram_sessions"}


def test_qa_block_releases_no_document_and_erases_the_case() -> None:
    class BlockingEngine:
        def process(self, raw_text: str):
            raise LegalQABlocked("blocking mismatch")

    runtime, api, store = _consented_runtime(BlockingEngine())
    runtime.handle_update(_message("ТОО А не оплатило услуги на 5 000 000 тенге."))

    assert any("Final Legal QA" in value for value in api.sent)
    # No draft, no readiness verdict and no surviving case text.
    assert not any("ИСК" in value for value in api.sent)
    assert store.get(7).case_buffer is None


def test_unsupported_workflow_is_refused_rather_than_substituted() -> None:
    class UnsupportedEngine:
        def process(self, raw_text: str):
            raise NotImplementedError("claim/labour")

    runtime, api, store = _consented_runtime(UnsupportedEngine())
    runtime.handle_update(_message("Меня незаконно уволили, что делать?"))

    assert any("не будет подменён" in value for value in api.sent)
    assert store.get(7).case_buffer is None


def test_transport_forwards_user_text_verbatim_and_relays_engine_verdict() -> None:
    class RecordingEngine:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def process(self, raw_text: str):
            self.calls.append(raw_text)
            return SimpleNamespace(
                document=SimpleNamespace(
                    readiness=ReadinessStatus.LAWYER_REVIEW_DRAFT,
                    needs_verification=["state_duty", "jurisdiction"],
                    text="ИСК\nИстец: ТОО A",
                )
            )

    engine = RecordingEngine()
    runtime, api, _ = _consented_runtime(engine)
    runtime.handle_update(_message("ТОО А не оплатило услуги."))

    # The handler adds no legal content of its own to the engine input.
    assert engine.calls == ["ТОО А не оплатило услуги."]
    # NEEDS_VERIFICATION items are relayed, never resolved by the transport.
    assert any("state_duty, jurisdiction" in value for value in api.sent)
    assert any(ReadinessStatus.LAWYER_REVIEW_DRAFT.value in value for value in api.sent)


def test_one_failing_update_does_not_block_the_polling_queue() -> None:
    class ExplodingStore:
        """Simulates an unreachable or unreadable session backend."""

        def get(self, user_id: int):
            raise RuntimeError("session backend unavailable")

        def save(self, user_id: int, session) -> None: ...

        def reset(self, user_id: int, *, language: str = "ru"):
            raise RuntimeError("session backend unavailable")

        def clear_case(self, user_id: int):
            raise RuntimeError("session backend unavailable")

        def delete(self, user_id: int) -> None: ...

    stop = Event()

    class PoisonAPI:
        def __init__(self) -> None:
            self.offsets: list[int | None] = []

        def get_me(self):
            return {"id": 1}

        def delete_webhook(self, *, drop_pending_updates: bool = False) -> bool:
            return True

        def set_my_commands(self, commands) -> bool:
            return True

        def get_updates(self, *, offset, timeout_seconds):
            self.offsets.append(offset)
            if len(self.offsets) > 3:
                stop.set()
                return []
            return [_message("привет"), {"update_id": 5, "message": _message("ещё")["message"]}]

        def send_message(self, *args, **kwargs) -> None: ...

        def answer_callback_query(self, callback_query_id: str) -> None: ...

    api = PoisonAPI()
    runtime = TelegramRuntime(
        api=api,
        engine=SimpleNamespace(process=lambda text: None),
        sessions=ExplodingStore(),
        poll_timeout_seconds=0,
    )
    runtime.run_forever(stop_event=stop)

    # Without confirming the offset Telegram would redeliver the same update forever and the
    # bot would stop serving every other user.
    assert api.offsets[0] is None
    assert api.offsets[1] == 6
    assert all(offset == 6 for offset in api.offsets[1:])


def test_session_state_is_persisted_through_the_store_not_only_in_memory() -> None:
    """Every language/consent/state/case_buffer change must reach SessionStore.save()."""

    class RecordingStore(InMemorySessionStore):
        def __init__(self) -> None:
            super().__init__()
            self.saved: list[tuple[str, str | None, str, str | None]] = []

        def save(self, user_id: int, session) -> None:
            super().save(user_id, session)
            self.saved.append(
                (session.language, session.consent_version, session.state.value, session.case_buffer)
            )

    class ClarifyingEngine:
        def process(self, raw_text: str):
            from korgan_legal_ai.domain.exceptions import ClarificationRequired

            raise ClarificationRequired(["Уточните дату"])

    store = RecordingStore()
    runtime = TelegramRuntime(api=FakeAPI(), engine=ClarifyingEngine(), sessions=store)
    runtime.handle_update(_message("/start"))
    runtime.handle_update(_callback("lang:kk"))
    runtime.handle_update(_callback("consent:accept"))
    runtime.handle_update(_callback("flow:claim"))
    runtime.handle_update(_message("Долг 1 000 000 тенге."))

    languages = {entry[0] for entry in store.saved}
    consents = {entry[1] for entry in store.saved}
    states = {entry[2] for entry in store.saved}
    buffers = {entry[3] for entry in store.saved}

    assert "kk" in languages
    assert runtime.privacy_version in consents
    assert SessionState.AWAITING_CLAIM.value in states
    assert SessionState.AWAITING_CLARIFICATION.value in states
    assert "Долг 1 000 000 тенге." in buffers
