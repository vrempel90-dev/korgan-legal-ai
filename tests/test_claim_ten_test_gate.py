from __future__ import annotations

from korgan.claim_money_ledger import build_claim_money_ledger
from korgan.claim_ten_test_gate import (
    TEN_TEST_OBJECTIVE,
    ensure_cost_slots,
    ensure_gap_markers,
    evaluate_claim_ten_tests,
    rewrite_duplicate_transitions,
)
from korgan.legal_types import ClaimDraft, LegalResearch, VerificationStatus


def _research() -> LegalResearch:
    return LegalResearch(
        status=VerificationStatus.VERIFIED,
        applicable_law=[],
        procedural_requirements=[],
        verified_claims=[
            "Статья 616 ГК РК регулирует договор подряда и обязанность выполнить работу.",
            "Статья 293 ГК РК регулирует договорную неустойку за нарушение обязательства.",
            "Статья 29 ГПК РК: иск предъявляется по месту нахождения ответчика.",
        ],
        unverified_claims=[],
        source_urls=["https://adilet.zan.kz/rus/docs/example"],
        notes=[],
    )


def _draft() -> ClaimDraft:
    return ClaimDraft(
        status=VerificationStatus.VERIFIED,
        title="И С К о взыскании задолженности и договорной неустойки",
        court="[ДАННЫЕ: точное наименование суда]",
        claimant=["ТОО «СтройИнжиниринг KZ»", "[ДАННЫЕ: БИН истца]", "[ДАННЫЕ: адрес истца]"],
        defendant=["ТОО «Астана Девелопмент»", "[ДАННЫЕ: БИН ответчика]", "[ДАННЫЕ: адрес ответчика]"],
        price_of_claim="9 240 000 тенге",
        state_duty="277 200 тенге (3% от цены иска)",
        late_interest="",
        facts=[
            "15.03.2026 между сторонами заключен Договор подряда № 07/26 на выполнение монтажных работ стоимостью 8 400 000 тенге.",
            "30.04.2026 сторонами подписан акт выполненных работ; замечаний к работам заказчик не заявил.",
            "Оплата в установленный договором срок не произведена, в связи с чем образовалась задолженность 8 400 000 тенге.",
            "Договором предусмотрена неустойка 0,1% за каждый календарный день просрочки.",
            "Расчёт договорной неустойки: 8 400 000 тенге × 0,1% × 100 календарных дней = 840 000 тенге.",
            "10.06.2026 истцом направлена досудебная претензия, однако задолженность не погашена.",
            "Обе организации зарегистрированы в городе Астана, что используется для определения подсудности.",
        ],
        legal_basis=[
            "Статья 616 ГК РК применяется к договору подряда и обязанности оплатить принятый результат работ.",
            "Статья 293 ГК РК применяется к согласованной сторонами договорной неустойке 0,1% за просрочку оплаты.",
            "Статья 29 ГПК РК применяется к подсудности по месту нахождения ответчика в городе Астана.",
        ],
        requests=[
            "Взыскать с ответчика основной долг в размере 8 400 000 тенге.",
            "Взыскать с ответчика договорную неустойку в размере 840 000 тенге.",
        ],
        attachments=[
            "Договор подряда № 07/26 от 15.03.2026.",
            "Акт выполненных работ от 30.04.2026.",
            "Досудебная претензия от 10.06.2026.",
        ],
        verification_notes=[],
        source_urls=[],
    )


def _context() -> str:
    return (
        "ТОО «СтройИнжиниринг KZ» и ТОО «Астана Девелопмент» заключили Договор подряда № 07/26 от 15.03.2026 "
        "на монтажные работы стоимостью 8 400 000 тенге. 30.04.2026 подписан акт выполненных работ. "
        "Оплата не произведена. Договором предусмотрена неустойка 0,1% за каждый календарный день просрочки. "
        "Неустойка за заявленный период составляет 840 000 тенге. 10.06.2026 направлена досудебная претензия. "
        "Обе организации зарегистрированы в городе Астана."
    )


def test_objective_contains_all_ten_tests_and_legal_cost_correction():
    for index in range(1, 11):
        assert f"Т{index}." in TEN_TEST_OBJECTIVE
    assert "Госпошлина и расходы представителя — судебные расходы" in TEN_TEST_OBJECTIVE
    assert "Судебные расходы в цену иска не включай" in TEN_TEST_OBJECTIVE


def test_cost_slots_are_added_as_honest_data_gaps_without_changing_claim_price_ledger():
    draft = _draft()
    ensure_cost_slots(_context(), draft)

    prayer = "\n".join(draft.requests)
    assert "государственной пошлины" in prayer
    assert "расходы на представителя" in prayer
    assert "[ДАННЫЕ:" in prayer

    ledger = build_claim_money_ledger(draft.requests)
    assert ledger.total == 9_240_000
    assert not ledger.unresolved_requests


def test_missing_party_requisites_use_data_markers_not_invented_values():
    draft = _draft()
    draft.claimant = ["ТОО «СтройИнжиниринг KZ»"]
    draft.defendant = ["ТОО «Астана Девелопмент»"]
    draft.court = ""
    ensure_gap_markers(_context(), draft)

    assert draft.court == "[ДАННЫЕ: точное наименование суда]"
    assert "[ДАННЫЕ: БИН истца]" in draft.claimant
    assert "[ДАННЫЕ: адрес истца]" in draft.claimant
    assert "[ДАННЫЕ: БИН ответчика]" in draft.defendant
    assert "[ДАННЫЕ: адрес ответчика]" in draft.defendant
    assert not any("000000" in item for item in [*draft.claimant, *draft.defendant])


def test_duplicate_petition_transition_is_rewritten_not_deleted():
    draft = _draft()
    draft.facts.append("На основании изложенного ПРОШУ СУД: взыскать предусмотренные договором суммы.")
    before = len(draft.facts)
    rewrite_duplicate_transitions(draft)
    assert len(draft.facts) == before
    assert all("ПРОШУ СУД" not in item.upper() for item in draft.facts)
    assert any("необходимость заявленных способов судебной защиты" in item for item in draft.facts)


def test_complete_debt_claim_scores_ten_of_ten_with_honest_cost_markers():
    draft = _draft()
    ensure_cost_slots(_context(), draft)
    ensure_gap_markers(_context(), draft)
    rewrite_duplicate_transitions(draft)

    result = evaluate_claim_ten_tests(_context(), _research(), draft)
    assert result.score == 10, {name: result.evidence[name] for name in result.failed}
    assert result.failed == []
