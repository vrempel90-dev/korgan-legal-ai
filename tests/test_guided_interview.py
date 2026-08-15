"""The guided dialogue collects facts deterministically and refuses to draft while incomplete."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from korgan_legal_ai.blueprints.interview import UNKNOWN, field_by_id
from korgan_legal_ai.blueprints.registry import (
    CLAIM_DEBT_RECOVERY,
    PRETRIAL_DEMAND,
    RESPONSE,
)
from korgan_legal_ai.domain.models import EvidenceKind, FilingMode, PartyRole, RepresentativeKind
from korgan_legal_ai.interview import (
    InterviewState,
    build_locked_case,
    build_routing,
    classify_evidence,
    parse_answer,
)

CLAIM_ANSWERS = {
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


def _parsed(blueprint, answers: dict[str, str]) -> dict[str, object]:
    """Answers as the dialogue stores them: validated and typed, never raw user text."""
    return _run_interview(blueprint, answers).answers


def _run_interview(blueprint, answers: dict[str, str]) -> InterviewState:
    state = InterviewState(blueprint_key=blueprint.key)
    while True:
        field = state.next_field()
        if field is None:
            return state
        parsed = parse_answer(field, answers.get(field.id, "не знаю"))
        assert parsed.ok, f"{field.id}: {parsed.error}"
        state.record(field.id, parsed.value)


def test_dialogue_collects_every_applicable_question_then_completes() -> None:
    state = _run_interview(CLAIM_DEBT_RECOVERY, CLAIM_ANSWERS)

    answered, total = state.progress()
    assert answered == total
    assert state.missing_required() == []


def test_generation_is_blocked_while_a_required_answer_is_missing() -> None:
    state = InterviewState(blueprint_key=CLAIM_DEBT_RECOVERY.key)
    state.record("author_name", "ТОО «Арман Логистикс»")

    missing = {field.id for field in state.missing_required()}

    # The dialogue knows what is still outstanding before a single line of the document is written.
    assert "opponent_name" in missing
    assert "circumstances" in missing
    assert state.next_field() is not None


def test_a_required_answer_that_cannot_be_unknown_is_rejected() -> None:
    """Some facts cannot be guessed at all, so "не знаю" is not an accepted answer for them."""
    parsed = parse_answer(field_by_id("circumstances"), "не знаю")

    assert not parsed.ok
    assert "не подставляет" in parsed.error


def test_unknown_is_recorded_as_undetermined_rather_than_defaulted() -> None:
    parsed = parse_answer(field_by_id("author_bin"), "не знаю")

    assert parsed.ok
    assert parsed.unknown
    assert parsed.value == UNKNOWN

    answers = {**_parsed(CLAIM_DEBT_RECOVERY, CLAIM_ANSWERS), "author_bin": UNKNOWN}
    case = build_locked_case(CLAIM_DEBT_RECOVERY, answers)
    # An unknown identifier stays absent instead of becoming a plausible-looking number.
    assert case.parties[0].iin_bin is None


def test_explicit_none_is_not_the_same_as_unknown() -> None:
    """"Нет" is a determined fact and must not become a verification gap."""
    none_answer = parse_answer(field_by_id("penalty_rate"), "нет")
    unknown_answer = parse_answer(field_by_id("penalty_rate"), "не знаю")

    assert none_answer.ok and none_answer.value is None and not none_answer.unknown
    assert unknown_answer.ok and unknown_answer.unknown


def test_unparseable_amounts_and_dates_are_re_asked_not_guessed() -> None:
    assert not parse_answer(field_by_id("contract_amount"), "около трёх миллионов").ok
    assert not parse_answer(field_by_id("obligation_due_date"), "где-то в июне").ok
    assert not parse_answer(field_by_id("author_bin"), "18034001").ok


def test_dependent_questions_appear_only_when_their_trigger_applies() -> None:
    state = InterviewState(blueprint_key=CLAIM_DEBT_RECOVERY.key)
    state.record("pretrial_required", "no")
    applicable = {field.id for field in state.applicable_fields()}
    assert "pretrial_sent_date" not in applicable

    state.record("pretrial_required", "yes")
    applicable = {field.id for field in state.applicable_fields()}
    assert "pretrial_sent_date" in applicable


def test_changing_a_trigger_drops_the_answer_it_invalidated() -> None:
    state = InterviewState(blueprint_key=CLAIM_DEBT_RECOVERY.key)
    state.record("filing_mode", "paper")
    state.record("copies_prepared", "yes")
    assert "copies_prepared" in state.answers

    state.record("filing_mode", "electronic")

    # A paper-only answer must not survive a switch to electronic filing.
    assert "copies_prepared" not in state.answers


def test_a_director_needs_no_separate_signing_power_question() -> None:
    state = InterviewState(blueprint_key=CLAIM_DEBT_RECOVERY.key)
    state.record("representative_kind", "director")

    assert "representative_can_sign" not in {f.id for f in state.applicable_fields()}

    case = build_locked_case(CLAIM_DEBT_RECOVERY, _parsed(CLAIM_DEBT_RECOVERY, CLAIM_ANSWERS))
    assert case.procedure.representative_kind == RepresentativeKind.DIRECTOR
    assert case.procedure.representative_can_sign_claim is True


def test_locked_case_is_built_from_typed_answers_without_a_model() -> None:
    case = build_locked_case(CLAIM_DEBT_RECOVERY, _parsed(CLAIM_DEBT_RECOVERY, CLAIM_ANSWERS))

    assert [party.role for party in case.parties] == [PartyRole.CLAIMANT, PartyRole.DEFENDANT]
    assert case.parties[0].name == "ТОО «Арман Логистикс»"
    assert case.financials.contract_amount == Decimal("3600000")
    assert [(p.amount, p.paid_on) for p in case.financials.payment_schedule] == [
        (Decimal("1200000"), date(2026, 3, 15))
    ]
    assert case.financials.penalty_rate_percent_per_day == Decimal("0.1")
    assert case.procedure.obligation_due_date == date(2026, 6, 3)
    assert case.procedure.pretrial_demand_sent_date == date(2026, 6, 20)
    assert case.procedure.filing_mode == FilingMode.ELECTRONIC
    # Raw text is never carried into a guided case: there is no prose for a model to re-read.
    assert case.raw_text == ""


def test_attachments_are_classified_by_explicit_wording_only() -> None:
    assert classify_evidence("Договор перевозки № 14") == EvidenceKind.CONTRACT
    assert classify_evidence("Акт оказанных услуг") == EvidenceKind.PRIMARY_DOCUMENT
    assert classify_evidence("Претензия от 20.06.2026") == EvidenceKind.PRETRIAL_DEMAND
    assert classify_evidence("Чек об отправке претензии") == EvidenceKind.PRETRIAL_DELIVERY
    # A state-duty receipt is also a "квитанция"; the filing fee must not read as proof of service.
    assert classify_evidence("Квитанция об уплате госпошлины") == EvidenceKind.STATE_DUTY_PAYMENT
    assert classify_evidence("Приказ о назначении руководителя") == EvidenceKind.AUTHORITY
    assert classify_evidence("Справка о регистрации") == EvidenceKind.REGISTRATION
    # Nothing recognisable stays uncategorised rather than being forced into a category.
    assert classify_evidence("Служебная записка") == EvidenceKind.OTHER


def test_routing_for_a_guided_request_is_the_user_choice() -> None:
    routing = build_routing(CLAIM_DEBT_RECOVERY)

    assert routing.document_type == CLAIM_DEBT_RECOVERY.document_type
    assert routing.confidence == 1.0


def test_every_registered_blueprint_can_be_completed_from_its_own_questions() -> None:
    """A new document type is usable through the dialogue without transport changes."""
    generic = {
        "author_name": "ТОО «Альфа»",
        "opponent_name": "ТОО «Бета»",
        "basis": "договор поставки № 7 от 01.02.2026",
        "circumstances": "Товар поставлен; оплата не поступила",
        "contract_amount": "1000000",
        "payments": "нет",
        "obligation_due_date": "01.05.2026",
        "evidence_list": "договор, накладная",
        "case_number": "2-1234/2026, СМЭС города Алматы",
        "contested_act": "решение от 01.04.2026 № 5",
        "motion_request": "Истребовать доказательства у третьего лица",
        "response_position": "Требования не признаю; товар не поставлен",
        "contract_subject": "Поставка товара по заявкам покупателя",
        "representative_kind": "Руководитель организации",
        "representative_name": "Асанов А.А.",
        "filing_mode": "Электронно (судебный кабинет)",
    }
    for blueprint in (CLAIM_DEBT_RECOVERY, PRETRIAL_DEMAND, RESPONSE):
        state = _run_interview(blueprint, generic)
        assert state.missing_required() == []
        case = build_locked_case(blueprint, state.answers)
        assert len(case.parties) == 2
        assert case.facts


def test_interview_state_survives_a_serialization_round_trip() -> None:
    state = _run_interview(CLAIM_DEBT_RECOVERY, CLAIM_ANSWERS)

    restored = InterviewState.deserialize(state.serialize())

    assert restored is not None
    assert restored.answers == state.answers
    assert restored.blueprint_key == state.blueprint_key


def test_unreadable_stored_state_is_discarded_rather_than_partially_trusted() -> None:
    assert InterviewState.deserialize("KORGAN_INTERVIEW_V1\n{broken") is None
    assert InterviewState.deserialize("KORGAN_INTERVIEW_V1\n{\"blueprint\": \"nope\"}") is None
    # Plain case text from the free-text path is not an interview and must not be read as one.
    assert InterviewState.deserialize("ТОО А не оплатило услуги") is None
