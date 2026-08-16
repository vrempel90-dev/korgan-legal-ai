"""Regression: the clarification dialogue must never repeat itself verbatim.

Reproduction from the field. The bot asked:

    Уточните значение поля роль стороны ТОО «Жетысу Строй»: получено неподдерживаемое значение.
    Уточните значение поля роль стороны ТОО «Прогресс Инжиниринг»: получено неподдерживаемое значение.
    Уточните значение поля representative_kind: получено неподдерживаемое значение.
    Ответьте одним сообщением.

The user answered in the bot's own vocabulary — "истец", "ответчик", "директор ... на основании
устава" — and the bot repeated the identical request. The cause was not lost dialogue state: the
answer did reach the extractor. `PartyRole("истец")` simply raised ValueError, because the enum only
accepted the internal English codes, so no reply phrased in the question's own terms could ever pass.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from korgan_legal_ai.calculations.service import CalculationLayer
from korgan_legal_ai.domain.models import (
    DocumentType,
    FilingMode,
    LegalArea,
    PartyRole,
    RepresentativeKind,
    RoutingDecision,
)
from korgan_legal_ai.drafting.debt_claim import DebtClaimDrafter
from korgan_legal_ai.fact_lock.service import (
    FactLockService,
    FactLockWireExtraction,
)
from korgan_legal_ai.fact_lock.vocabulary import normalize_enum
from korgan_legal_ai.orchestration.debt_claim import DebtClaimWorkflow
from korgan_legal_ai.orchestration.engine import LegalEngine
from korgan_legal_ai.procedural.checker import ProceduralChecker
from korgan_legal_ai.research.gateway import CitationGateway
from korgan_legal_ai.telegram.runtime import TelegramRuntime
from korgan_legal_ai.telegram.session import InMemorySessionStore, SessionState

CLAIMANT = "ТОО «Прогресс Инжиниринг»"
DEFENDANT = "ТОО «Жетысу Строй»"

CASE_TEXT = (
    "Взыскание долга по договору подряда № 12 от 03.02.2026. "
    "ТОО «Прогресс Инжиниринг», БИН 180340012345, г. Астана, ул. Кабанбай батыра, 12, "
    "выполнило работы на 14 000 000 тенге, работы приняты по акту от 20.04.2026. "
    "ТОО «Жетысу Строй», БИН 200140098765, г. Алматы, пр. Достык, 44, "
    "оплатило 6 000 000 тенге 30.04.2026, остаток не погашен. "
    "Срок оплаты по договору — 25.04.2026. Неустойка 0,1% в день, но не более 10% от суммы долга. "
    "Есть договор подряда, акт выполненных работ, счёт на оплату, справка о регистрации, "
    "приказ о назначении руководителя. Подача электронно через судебный кабинет."
)

# The exact answer from the reproduction.
USER_CLARIFICATION = (
    "ТОО «Прогресс Инжиниринг» — истец (Исполнитель по договору, которому не оплатили работы). "
    "ТОО «Жетысу Строй» — ответчик (Заказчик по договору, должник). "
    "Представитель истца — директор Абдрахманов Е.С., действует на основании устава "
    "(без доверенности)."
)


class RussianSpeakingExtractor:
    """Stands in for the real extractor, which returns Russian words for a Russian case.

    The first pass leaves the roles unstated, as the original message did. Once the user says who
    is who, the extractor reports it in the words the user used — which is exactly what used to be
    rejected.
    """

    def __init__(self) -> None:
        self.calls: list[str] = []

    def parse(self, *, model, system, user, schema):
        self.calls.append(user)
        roles_known = "истец" in user.lower()
        return FactLockWireExtraction.model_validate(
            {
                "parties": [
                    {
                        "name": CLAIMANT,
                        "role": "истец" if roles_known else "сторона договора",
                        "iin_bin": "180340012345",
                        "address": "г. Астана, ул. Кабанбай батыра, 12",
                    },
                    {
                        "name": DEFENDANT,
                        "role": "ответчик" if roles_known else "сторона договора",
                        "iin_bin": "200140098765",
                        "address": "г. Алматы, пр. Достык, 44",
                    },
                ],
                "facts": [
                    {"id": "f1", "statement": "Работы по договору подряда № 12 от 03.02.2026 выполнены"},
                    {"id": "f2", "statement": "Работы приняты заказчиком по акту"},
                    {"id": "f3", "statement": "Оплата поступила частично"},
                ],
                "evidence": [
                    {"title": "Договор подряда № 12", "kind": "договор", "supports_fact_ids": ["f1"]},
                    {"title": "Акт выполненных работ", "kind": "акт", "supports_fact_ids": ["f2"]},
                ],
                "financials": {
                    "contract_amount": "14000000",
                    "payments": ["6000000"],
                    "penalty_rate_percent_per_day": "0.1",
                    "penalty_cap_percent_of_principal": "10",
                    "currency": "KZT",
                },
                "procedure": {
                    "obligation_due_date": "25.04.2026",
                    "representative_kind": (
                        "директор, действует на основании устава" if roles_known else "не указано кем"
                    ),
                    "representative_name": "Абдрахманов Е.С." if roles_known else None,
                    "filing_mode": "электронно",
                },
                "ambiguities": [],
            }
        )


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
            "from": {"id": 42},
            "chat": {"id": 42, "type": "private"},
            "text": value,
        },
    }


def _callback(data: str) -> dict:
    return {
        "update_id": 2,
        "callback_query": {
            "id": "cb",
            "from": {"id": 42},
            "message": {"chat": {"id": 42, "type": "private"}},
            "data": data,
        },
    }


class StaticRouter:
    def route(self, case):
        return RoutingDecision(
            document_type=DocumentType.CLAIM,
            legal_area=LegalArea.DEBT_RECOVERY,
            confidence=1.0,
            rationale="regression fixture",
        )


def _runtime() -> tuple[TelegramRuntime, FakeAPI, InMemorySessionStore, RussianSpeakingExtractor]:
    provider = RussianSpeakingExtractor()
    engine = LegalEngine(
        fact_lock=FactLockService(provider, "test-model"),
        router=StaticRouter(),
        debt_claim=DebtClaimWorkflow(
            procedural=ProceduralChecker(CitationGateway()),
            drafter=DebtClaimDrafter(),
            calculations=CalculationLayer(),
            as_of_date_provider=lambda: date(2026, 8, 15),
        ),
    )
    api = FakeAPI()
    store = InMemorySessionStore()
    runtime = TelegramRuntime(api=api, engine=engine, sessions=store)
    runtime.handle_update(_message("/start"))
    runtime.handle_update(_callback("lang:ru"))
    runtime.handle_update(_callback("consent:accept"))
    runtime.handle_update(_callback("flow:claim"))
    return runtime, api, store, provider


def _clarifications(api: FakeAPI) -> list[str]:
    return [value for value in api.sent if "Нужно уточнить" in value]


def test_answering_a_clarification_makes_progress_instead_of_repeating_it() -> None:
    runtime, api, store, provider = _runtime()

    runtime.handle_update(_message(CASE_TEXT))
    first_round = _clarifications(api)
    assert first_round, "the incomplete case must produce a clarification request"
    assert store.get(42).state == SessionState.AWAITING_CLARIFICATION

    runtime.handle_update(_message(USER_CLARIFICATION))
    second_round = _clarifications(api)

    # The bug: the identical request came back, as if the answer had never been read.
    if len(second_round) > 1:
        assert second_round[1] != second_round[0], (
            "the clarification request repeated verbatim — the answer made no progress"
        )
    # The answer resolved the open questions, so the dialogue moved on to the document.
    assert not any("роль стороны" in value for value in second_round[1:])
    assert any("ИСКОВОЕ ЗАЯВЛЕНИЕ" in value for value in api.sent)

    # The answer really did reach the extractor rather than being dropped by the transport.
    assert any("истец" in call.lower() for call in provider.calls)


def test_the_answer_binds_to_the_fields_that_were_asked_about() -> None:
    runtime, api, store, _ = _runtime()

    runtime.handle_update(_message(CASE_TEXT))
    runtime.handle_update(_message(USER_CLARIFICATION))

    document = next(value for value in api.sent if "ИСКОВОЕ ЗАЯВЛЕНИЕ" in value)
    # Each side is printed under the label matching the role the user stated, not swapped.
    assert f"Истец: {CLAIMANT}" in document
    assert f"Ответчик: {DEFENDANT}" in document
    assert "Абдрахманов Е.С." in document


def test_the_whole_cycle_reaches_a_word_file() -> None:
    runtime, api, store, _ = _runtime()

    runtime.handle_update(_message(CASE_TEXT))
    runtime.handle_update(_message(USER_CLARIFICATION))

    # 14 000 000 − 6 000 000 = 8 000 000 debt; the penalty ceiling is 10% of it.
    document = next(value for value in api.sent if "ИСКОВОЕ ЗАЯВЛЕНИЕ" in value)
    assert "Основной долг: 8000000 KZT" in document
    assert api.documents, "the approved document must be delivered as a Word file"
    filename, payload = api.documents[0]
    assert filename.endswith(".docx")
    assert payload[:2] == b"PK"
    assert store.get(42).case_buffer is None


def test_the_terms_the_bot_uses_in_its_question_are_accepted_as_answers() -> None:
    """Whatever wording the question uses, an answer in that wording has to be understood."""
    assert normalize_enum(PartyRole, "истец") == PartyRole.CLAIMANT
    assert normalize_enum(PartyRole, "Истец") == PartyRole.CLAIMANT
    assert normalize_enum(PartyRole, "ответчик") == PartyRole.DEFENDANT
    assert normalize_enum(RepresentativeKind, "директор") == RepresentativeKind.DIRECTOR


def test_contract_role_pairs_resolve_to_the_side_that_claims_payment() -> None:
    for word in ("исполнитель", "подрядчик", "поставщик", "продавец", "арендодатель", "займодавец"):
        assert normalize_enum(PartyRole, word) == PartyRole.CREDITOR, word
    for word in ("заказчик", "покупатель", "арендатор", "заёмщик", "плательщик"):
        assert normalize_enum(PartyRole, word) == PartyRole.DEBTOR, word


def test_a_direct_procedural_term_wins_over_a_contract_role_in_the_same_answer() -> None:
    """"Истец (Заказчик по договору)" is a claimant; the contract role is only context."""
    assert (
        normalize_enum(PartyRole, "истец (Заказчик по договору, которому поставили брак)")
        == PartyRole.CLAIMANT
    )
    assert (
        normalize_enum(PartyRole, "ответчик (Исполнитель, не выполнивший работы)")
        == PartyRole.DEFENDANT
    )


def test_authority_wording_is_understood_without_a_power_of_attorney() -> None:
    for wording in (
        "директор, действует на основании устава",
        "по уставу",
        "первый руководитель",
        "генеральный директор",
    ):
        assert normalize_enum(RepresentativeKind, wording) == RepresentativeKind.DIRECTOR, wording
    assert normalize_enum(RepresentativeKind, "представитель по доверенности № 5") == (
        RepresentativeKind.OTHER
    )
    assert normalize_enum(RepresentativeKind, "адвокат Ким В.П.") == RepresentativeKind.ADVOCATE


def test_an_unrecognised_answer_says_what_is_expected_instead_of_repeating_itself() -> None:
    ambiguities: list[str] = []
    from korgan_legal_ai.fact_lock.service import _enum_value

    _enum_value(
        PartyRole,
        "какая-то непонятная роль",
        field_name="роль стороны ТОО «Альфа»",
        ambiguities=ambiguities,
        default=PartyRole.OTHER,
    )

    assert len(ambiguities) == 1
    message = ambiguities[0]
    # The old message named neither the offending value nor any accepted one.
    assert "какая-то непонятная роль" in message
    assert "истец" in message and "ответчик" in message
    assert "неподдерживаемое значение" not in message


def test_filing_mode_and_evidence_kinds_accept_ordinary_wording() -> None:
    assert normalize_enum(FilingMode, "электронно, через судебный кабинет") == FilingMode.ELECTRONIC
    assert normalize_enum(FilingMode, "на бумаге") == FilingMode.PAPER
    assert normalize_enum(FilingMode, "неизвестно как") is None
