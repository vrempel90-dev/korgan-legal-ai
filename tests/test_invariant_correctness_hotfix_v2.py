from __future__ import annotations

from datetime import date

from korgan.invariant_correctness_hotfix_v2 import (
    _penalty_line,
    apply_money_ledger_to_claim_v2,
    apply_money_ledger_to_pretrial_v2,
    classify_issue_v2,
)
from korgan.legal_types import ClaimDraft, VerificationStatus
from korgan.pretrial import PretrialDraft
from korgan.production_invariants_v2 import BlockerClass, calc_contractual_penalty


FIXTURE = (
    "Основной долг 3 250 000 тенге. "
    "По договору неустойка 0,2% в день, потолок 20%. "
    "Просрочка с 08.03.2026."
)


def _claim() -> ClaimDraft:
    return ClaimDraft(
        status=VerificationStatus.VERIFIED,
        title="ИСКОВОЕ ЗАЯВЛЕНИЕ",
        court="Суд",
        claimant=["Истец"],
        defendant=["Ответчик"],
        price_of_claim="",
        facts=["Факт"],
        legal_basis=[],
        requests=["Обязать ответчика исполнить обязательство."],
        attachments=[],
        verification_notes=[],
        source_urls=[],
    )


def _pretrial() -> PretrialDraft:
    return PretrialDraft(
        status=VerificationStatus.VERIFIED,
        title="ДОСУДЕБНАЯ ПРЕТЕНЗИЯ",
        sender=["Отправитель"],
        recipient=["Получатель"],
        facts=["Факт"],
        legal_basis=[],
        demands=["Исполнить обязательство."],
        deadline="",
        consequences=[],
        attachments=[],
    )


def test_missing_user_fact_wins_even_when_issue_mentions_article() -> None:
    issue = "не указан адрес ответчика для соблюдения ст. 148 ГПК РК"
    assert classify_issue_v2(issue).blocker_class == BlockerClass.NEEDS_USER_DATA


def test_actual_contract_missing_fact_blockers_are_user_resolvable() -> None:
    for issue in (
        "не идентифицированы обе стороны договора",
        "нет реквизитов/подписного блока обеих сторон",
        "не заполнены место/дата заключения договора",
    ):
        assert classify_issue_v2(issue).blocker_class == BlockerClass.NEEDS_USER_DATA


def test_generated_article_paraphrase_remains_internal_quality() -> None:
    issue = "статья 469 ГК РК: пересказ обобщает узкое условие нормы"
    assert classify_issue_v2(issue).blocker_class == BlockerClass.INTERNAL_QUALITY


def test_claim_principal_is_propagated_before_ledger_acceptance() -> None:
    draft = _claim()
    ledger = apply_money_ledger_to_claim_v2(FIXTURE, draft, as_of=date(2026, 8, 25))
    text = "\n".join(draft.requests)
    assert "3 250 000 тенге" in text
    assert "650 000 тенге" in text
    assert "15.06.2026" in text
    assert draft.price_of_claim == "3 900 000 тенге"
    assert ledger.total > 0


def test_pretrial_principal_is_propagated_too() -> None:
    draft = _pretrial()
    ledger = apply_money_ledger_to_pretrial_v2(FIXTURE, draft, as_of=date(2026, 8, 25))
    text = "\n".join(draft.demands)
    assert "3 250 000 тенге" in text
    assert "650 000 тенге" in text
    assert "15.06.2026" in text
    assert ledger.total > 0


def test_cap_is_not_described_as_reached_before_reach_date() -> None:
    penalty = calc_contractual_penalty(
        3_250_000,
        "0.2",
        date(2026, 3, 8),
        date(2026, 5, 1),
        cap_percent="20",
    )
    assert penalty.cap_reached_on == date(2026, 6, 15)
    line = _penalty_line(penalty, claim=True)
    assert "15.06.2026" not in line
    assert "ещё не достигнут" in line
    assert penalty.amount < 650_000
