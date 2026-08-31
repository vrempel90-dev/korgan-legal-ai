"""Ответ обязан разобрать каждое входящее требование, а не большинство.

Пять требований в иске или претензии — это пять самостоятельных предметов
позиции. Непустые claim_summary и objections ничего не доказывают: модель может
добросовестно разобрать четыре пункта, потерять пятый и всё равно выпустить
документ с оценкой 10.0. Молчание особенно опасно потому, что выглядит как
полный отзыв, хотя одно требование осталось без признания или возражения.

Источник требований здесь только исходные материалы, где явно обозначена
просительная часть. Любая сумма в фабуле требованием не становится. Покрытие
ищется во всём содержательном ответе, но не в claim_summary: простое переписывание
петитума ещё не является позицией по нему.
"""

from __future__ import annotations

from korgan.document_quality import assess_document_quality
from korgan.incoming_demand_coverage import uncovered_incoming_demands
from korgan.legal_types import LegalResearch, VerificationStatus
from korgan.pretrial_response import PretrialResponseDraft
from korgan.response_types import ResponseObjection, ResponseToClaimDraft

ADILET = "https://adilet.zan.kz/rus/docs/K940001000_"
COURT = "Специализированный межрайонный экономический суд города Астаны"
CONTEXT_HEAD = (
    "Истец: ТОО «АЛЬЯНС», БИН 180340012345.\n"
    "Ответчик: ТОО «СТРОЙ ГРУПП», БИН 200140012345.\n"
    "Цена договора составляла 9 900 000 тенге.\n"
)
FIVE_CLAIM_DEMANDS = (
    "ИСКОВЫЕ ТРЕБОВАНИЯ:\n"
    "1. Взыскать основной долг в размере 1 200 000 тенге.\n"
    "2. Взыскать неустойку в размере 240 000 тенге.\n"
    "3. Взыскать убытки в размере 310 000 тенге.\n"
    "4. Взыскать расходы на представителя в размере 150 000 тенге.\n"
    "5. Обязать ответчика вернуть оборудование марки K-5.\n"
    "Приложения: копия договора и накладной."
)
FIVE_PRETRIAL_DEMANDS = (
    "ТРЕБОВАНИЯ ПРЕТЕНЗИИ:\n"
    "1. Уплатить основной долг в размере 1 200 000 тенге.\n"
    "2. Уплатить неустойку в размере 240 000 тенге.\n"
    "3. Возместить убытки в размере 310 000 тенге.\n"
    "4. Возместить расходы на юридическую помощь в размере 150 000 тенге.\n"
    "5. Вернуть оборудование марки K-5.\n"
    "Приложения: копия договора и накладной."
)
FOUR_ANSWERS = [
    "Основной долг 1 200 000 тенге не признаётся: товарная накладная не подписана.",
    "Неустойка 240 000 тенге не подлежит взысканию: согласованный срок не нарушен.",
    "Убытки 310 000 тенге не подтверждены первичными документами.",
    "Расходы на представителя 150 000 тенге документально не подтверждены.",
]
FIFTH_ANSWER = "Требование вернуть оборудование марки K-5 не признаётся: оборудование истцу не передавалось."


def _research() -> LegalResearch:
    return LegalResearch(
        status=VerificationStatus.VERIFIED,
        applicable_law=[],
        procedural_requirements=[],
        verified_claims=[],
        unverified_claims=[],
        notes=[f"VERIFIED_COURT: {COURT}"],
        source_urls=[ADILET],
    )


def _response(*, answers: list[str]) -> ResponseToClaimDraft:
    return ResponseToClaimDraft(
        status=VerificationStatus.VERIFIED,
        title="ОТЗЫВ НА ИСКОВОЕ ЗАЯВЛЕНИЕ",
        court=COURT,
        case_number="7199-26-00-2/1234",
        claimant=["ТОО «АЛЬЯНС», БИН 180340012345"],
        defendant=["ТОО «СТРОЙ ГРУПП», БИН 200140012345"],
        claim_summary=[
            "Истец просит взыскать 1 200 000 тенге долга, 240 000 тенге неустойки, "
            "310 000 тенге убытков, 150 000 тенге расходов на представителя и вернуть "
            "оборудование марки K-5."
        ],
        position=["Исковые требования не признаются по следующим основаниям."],
        objections=[ResponseObjection(text=item) for item in answers],
        calculation_review=[
            "Расчёт долга 1 200 000 тенге, неустойки 240 000 тенге, убытков "
            "310 000 тенге и расходов 150 000 тенге проверен по каждому компоненту."
        ],
        legal_basis=["Обязательства исполняются в соответствии с условиями договора."],
        requests=["Отказать в удовлетворении исковых требований."],
        attachments=["Копия товарной накладной"],
        verification_notes=[],
        source_urls=[ADILET],
    )


def _pretrial_response(*, answers: list[str]) -> PretrialResponseDraft:
    return PretrialResponseDraft(
        status=VerificationStatus.VERIFIED,
        title="ОТВЕТ НА ДОСУДЕБНУЮ ПРЕТЕНЗИЮ",
        sender=["ТОО «СТРОЙ ГРУПП», БИН 200140012345"],
        recipient=["ТОО «АЛЬЯНС», БИН 180340012345"],
        reference="претензия от 05.03.2026 № 7",
        claim_summary=[
            "Заявитель требует уплатить 1 200 000 тенге долга, 240 000 тенге "
            "неустойки, 310 000 тенге убытков, 150 000 тенге расходов на юридическую "
            "помощь и вернуть оборудование марки K-5."
        ],
        position=["Требования претензии не признаются по следующим основаниям."],
        objections=answers,
        calculation_review=[
            "Расчёт долга 1 200 000 тенге, неустойки 240 000 тенге, убытков "
            "310 000 тенге и расходов 150 000 тенге проверен по каждому компоненту."
        ],
        legal_basis=["Обязательства исполняются в соответствии с условиями договора."],
        response_terms=["Оснований для добровольного исполнения требований не имеется."],
        attachments=["Копия товарной накладной"],
        verification_notes=[],
        source_urls=[ADILET],
    )


def test_five_incoming_claim_demands_with_only_four_answers_leave_one_uncovered() -> None:
    missing = uncovered_incoming_demands(CONTEXT_HEAD + FIVE_CLAIM_DEMANDS, FOUR_ANSWERS)

    assert len(missing) == 1
    assert "оборудован" in missing[0].lower()


def test_repeating_all_five_demands_in_summary_is_not_coverage() -> None:
    draft = _response(answers=FOUR_ANSWERS)

    missing = uncovered_incoming_demands(
        CONTEXT_HEAD + FIVE_CLAIM_DEMANDS,
        [*draft.claim_summary, *FOUR_ANSWERS],
        summaries=draft.claim_summary,
    )

    assert len(missing) == 1
    assert "оборудован" in missing[0].lower()


def test_all_five_incoming_claim_demands_are_covered_once_the_fifth_is_answered() -> None:
    assert uncovered_incoming_demands(
        CONTEXT_HEAD + FIVE_CLAIM_DEMANDS,
        [*FOUR_ANSWERS, FIFTH_ANSWER],
    ) == []


def test_money_in_facts_before_the_explicit_demand_section_is_not_an_extra_demand() -> None:
    assert uncovered_incoming_demands(
        CONTEXT_HEAD + FIVE_CLAIM_DEMANDS,
        [*FOUR_ANSWERS, FIFTH_ANSWER],
    ) == []


def test_response_gate_blocks_when_one_of_five_claim_demands_is_unanswered() -> None:
    report = assess_document_quality(
        "response_to_claim", CONTEXT_HEAD + FIVE_CLAIM_DEMANDS, _research(), _response(answers=FOUR_ANSWERS)
    )

    assert report.ready is False
    assert any("оборудован" in blocker.lower() for blocker in report.hard_blockers), report.hard_blockers


def test_response_gate_releases_coverage_once_all_five_demands_are_answered() -> None:
    report = assess_document_quality(
        "response_to_claim",
        CONTEXT_HEAD + FIVE_CLAIM_DEMANDS,
        _research(),
        _response(answers=[*FOUR_ANSWERS, FIFTH_ANSWER]),
    )

    assert not any("не дан содержательный ответ" in blocker for blocker in report.hard_blockers), report.hard_blockers


def test_pretrial_response_gate_blocks_when_one_of_five_demands_is_unanswered() -> None:
    report = assess_document_quality(
        "pretrial_response",
        CONTEXT_HEAD + FIVE_PRETRIAL_DEMANDS,
        _research(),
        _pretrial_response(answers=FOUR_ANSWERS),
    )

    assert report.ready is False
    assert any("оборудован" in blocker.lower() for blocker in report.hard_blockers), report.hard_blockers


def test_pretrial_response_gate_releases_coverage_once_all_five_demands_are_answered() -> None:
    report = assess_document_quality(
        "pretrial_response",
        CONTEXT_HEAD + FIVE_PRETRIAL_DEMANDS,
        _research(),
        _pretrial_response(answers=[*FOUR_ANSWERS, FIFTH_ANSWER]),
    )

    assert not any("не дан содержательный ответ" in blocker for blocker in report.hard_blockers), report.hard_blockers


def test_no_explicit_incoming_demand_section_means_no_coverage_guess() -> None:
    context = "Истец перечислил ответчику 1 200 000 тенге по договору от 12.01.2026."

    assert uncovered_incoming_demands(context, []) == []
