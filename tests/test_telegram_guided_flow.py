"""The Telegram guided dialogue: question by question, then the full legal pipeline."""
from __future__ import annotations

from datetime import date

from korgan_legal_ai.blueprints.registry import CLAIM_DEBT_RECOVERY
from korgan_legal_ai.calculations.service import CalculationLayer
from korgan_legal_ai.drafting.debt_claim import DebtClaimDrafter
from korgan_legal_ai.interview import InterviewState
from korgan_legal_ai.orchestration.debt_claim import DebtClaimWorkflow
from korgan_legal_ai.orchestration.engine import LegalEngine
from korgan_legal_ai.procedural.checker import ProceduralChecker
from korgan_legal_ai.research.gateway import CitationGateway
from korgan_legal_ai.telegram.runtime import TelegramRuntime
from korgan_legal_ai.telegram.session import InMemorySessionStore, SessionState

ANSWERS = {
    "author_name": "ТОО «Арман Логистикс»",
    "author_bin": "180340012345",
    "author_address": "г. Астана, ул. Кабанбай батыра, 12",
    "opponent_name": "ТОО «Нова Трейд»",
    "opponent_bin": "200140098765",
    "opponent_address": "г. Алматы, пр. Достык, 44",
    "basis": "договор перевозки № 14 от 12.02.2026",
    "circumstances": "Перевозка выполнена; акт подписан; оплата не поступила",
    "contract_amount": "3600000",
    "payments": "1200000 от 15.03.2026",
    "obligation_due_date": "03.06.2026",
    "penalty_rate": "0.1",
    "penalty_cap": "10",
    "other_amount": "нет",
    "pretrial_required": "да",
    "pretrial_sent_date": "20.06.2026",
    "representative_kind": "Руководитель организации",
    "representative_name": "Асанов А.А.",
    "filing_mode": "Электронно (судебный кабинет)",
    "evidence_list": "договор, акт оказанных услуг, претензия, чек об отправке претензии, "
    "квитанция об уплате госпошлины, справка о регистрации, приказ о назначении руководителя",
}


class FakeAPI:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self.documents: list[tuple[str, bytes]] = []

    def send_message(self, chat_id: int, value: str, *, reply_markup=None) -> None:
        self.sent.append(value)

    def send_document(self, chat_id: int, *, filename: str, data: bytes, caption: str) -> None:
        self.documents.append((filename, data))

    def answer_callback_query(self, callback_query_id: str) -> None:
        return None


def _message(value: str) -> dict:
    return {
        "update_id": 1,
        "message": {
            "from": {"id": 11},
            "chat": {"id": 11, "type": "private"},
            "text": value,
        },
    }


def _callback(data: str) -> dict:
    return {
        "update_id": 2,
        "callback_query": {
            "id": "cb",
            "from": {"id": 11},
            "message": {"chat": {"id": 11, "type": "private"}},
            "data": data,
        },
    }


def _engine() -> LegalEngine:
    workflow = DebtClaimWorkflow(
        procedural=ProceduralChecker(CitationGateway()),
        drafter=DebtClaimDrafter(),
        calculations=CalculationLayer(),
        as_of_date_provider=lambda: date(2026, 8, 15),
    )
    return LegalEngine(fact_lock=None, router=None, debt_claim=workflow)


def _consented() -> tuple[TelegramRuntime, FakeAPI, InMemorySessionStore]:
    api = FakeAPI()
    store = InMemorySessionStore()
    runtime = TelegramRuntime(api=api, engine=_engine(), sessions=store)
    runtime.handle_update(_message("/start"))
    runtime.handle_update(_callback("lang:ru"))
    runtime.handle_update(_callback("consent:accept"))
    return runtime, api, store


def _answer_everything(runtime: TelegramRuntime, store: InMemorySessionStore) -> None:
    while True:
        state = InterviewState.deserialize(store.get(11).case_buffer)
        if state is None:
            return
        field = state.next_field()
        if field is None:
            return
        runtime.handle_update(_message(ANSWERS.get(field.id, "не знаю")))


def test_guided_dialogue_runs_the_whole_cycle_to_a_word_file() -> None:
    runtime, api, store = _consented()

    runtime.handle_update(_callback("flow:interview"))
    runtime.handle_update(_callback(f"doctype:{CLAIM_DEBT_RECOVERY.key}"))
    assert store.get(11).state == SessionState.AWAITING_INTERVIEW

    _answer_everything(runtime, store)

    document = next(value for value in api.sent if "ИСКОВОЕ ЗАЯВЛЕНИЕ" in value)
    # The deterministic calculation, not the dialogue, produces every figure in the document.
    assert "Основной долг: 2400000 KZT" in document
    assert "Итого: 2575200.00 KZT" in document
    assert "в размере 2575200.00 KZT" in document

    assert api.documents, "a Word file must be delivered"
    filename, payload = api.documents[0]
    assert filename.startswith("KORGAN_isk_") and filename.endswith(".docx")
    assert payload[:2] == b"PK"

    # The verification queue is delivered separately from the document text.
    queue = next(value for value in api.sent if "Требует проверки" in value)
    assert "state_duty" not in queue and "подсудность" in queue

    # The unfinished-case buffer is erased once the request completes.
    assert store.get(11).case_buffer is None


def test_dialogue_asks_one_question_at_a_time_and_validates_each_answer() -> None:
    runtime, api, store = _consented()
    runtime.handle_update(_callback("flow:interview"))
    runtime.handle_update(_callback(f"doctype:{CLAIM_DEBT_RECOVERY.key}"))

    before = len(api.sent)
    runtime.handle_update(_message("ТОО «Арман Логистикс»"))
    asked = [value for value in api.sent[before:] if value.startswith("❓")]
    assert len(asked) == 1

    # Walk to the first amount question and give it a value that cannot be parsed.
    while True:
        state = InterviewState.deserialize(store.get(11).case_buffer)
        field = state.next_field()
        if field is None or field.id == "contract_amount":
            break
        runtime.handle_update(_message(ANSWERS.get(field.id, "не знаю")))

    runtime.handle_update(_message("примерно три с половиной миллиона"))

    assert any("Не удалось прочитать число" in value for value in api.sent)
    state = InterviewState.deserialize(store.get(11).case_buffer)
    # The unparseable answer was not stored under any interpretation.
    assert "contract_amount" not in state.answers


def test_no_document_is_produced_while_required_facts_are_missing() -> None:
    runtime, api, store = _consented()
    runtime.handle_update(_callback("flow:interview"))
    runtime.handle_update(_callback(f"doctype:{CLAIM_DEBT_RECOVERY.key}"))
    runtime.handle_update(_message("ТОО «Арман Логистикс»"))

    assert not any("ИСКОВОЕ ЗАЯВЛЕНИЕ" in value for value in api.sent)
    assert not api.documents
    state = InterviewState.deserialize(store.get(11).case_buffer)
    assert state.missing_required()


def test_back_command_reopens_the_previous_question() -> None:
    runtime, _api, store = _consented()
    runtime.handle_update(_callback("flow:interview"))
    runtime.handle_update(_callback(f"doctype:{CLAIM_DEBT_RECOVERY.key}"))
    runtime.handle_update(_message("ТОО «Арман Логистикс»"))

    state = InterviewState.deserialize(store.get(11).case_buffer)
    assert state.answers["author_name"] == "ТОО «Арман Логистикс»"

    runtime.handle_update(_message("/back"))

    state = InterviewState.deserialize(store.get(11).case_buffer)
    assert "author_name" not in state.answers
    assert state.next_field().id == "author_name"


def test_cancel_erases_collected_answers() -> None:
    runtime, _api, store = _consented()
    runtime.handle_update(_callback("flow:interview"))
    runtime.handle_update(_callback(f"doctype:{CLAIM_DEBT_RECOVERY.key}"))
    runtime.handle_update(_message("ТОО «Арман Логистикс»"))

    runtime.handle_update(_message("/cancel"))

    assert store.get(11).case_buffer is None


def test_a_stale_choice_button_cannot_overwrite_a_later_answer() -> None:
    runtime, _api, store = _consented()
    runtime.handle_update(_callback("flow:interview"))
    runtime.handle_update(_callback(f"doctype:{CLAIM_DEBT_RECOVERY.key}"))
    runtime.handle_update(_message("ТОО «Арман Логистикс»"))

    # A button belonging to a question that is not the pending one is ignored.
    runtime.handle_update(_callback("answer:filing_mode:paper"))

    state = InterviewState.deserialize(store.get(11).case_buffer)
    assert "filing_mode" not in state.answers
