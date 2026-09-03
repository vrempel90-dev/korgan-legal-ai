from __future__ import annotations

import asyncio
from datetime import date

from korgan import automatic_claim_calculations_runtime as runtime
from korgan import late_interest_hotfix as late
from korgan.legal_calc import NEEDS_CALCULATION_MARKER, parse_amount_kzt
from korgan.legal_types import ClaimDraft, LegalResearch, VerificationStatus


def _research(*, unverified: list[str] | None = None) -> LegalResearch:
    return LegalResearch(
        status=VerificationStatus.VERIFIED if not unverified else VerificationStatus.NEEDS_VERIFICATION,
        applicable_law=["ГК РК"],
        procedural_requirements=[],
        verified_claims=[
            "За просрочку денежного обязательства применяется неустойка. "
            "[основание: статья 353 ГК РК; источник: https://adilet.zan.kz/rus/docs/K940001000_/compare]"
        ],
        unverified_claims=list(unverified or []),
        source_urls=["https://adilet.zan.kz/rus/docs/K940001000_/compare"],
        notes=[],
    )


def _draft(*, verification_notes: list[str] | None = None) -> ClaimDraft:
    return ClaimDraft(
        status=VerificationStatus.VERIFIED,
        title="ИСКОВОЕ ЗАЯВЛЕНИЕ о взыскании задолженности",
        court="В суд: [уточняется]",
        claimant=["Истец: Иванов Иван Иванович, ИИН 900101300001"],
        defendant=["Ответчик: Петров Петр Петрович"],
        price_of_claim="1 000 000 тенге",
        facts=["Ответчик не возвратил основной долг."],
        legal_basis=[],
        requests=["Взыскать основной долг в размере 1 000 000 тенге."],
        attachments=[],
        verification_notes=list(verification_notes or []),
        source_urls=["https://adilet.zan.kz/rus/docs/K940001000_/compare"],
    )


def test_detects_overdue_money_claim_without_word_penalty():
    context = (
        "Истец: Иванов Иван Иванович, ИИН 900101300001\n"
        "Ответчик: Петров Петр Петрович\n"
        "По договору займа ответчик получил 1 000 000 тенге и должен был вернуть деньги до 10.01.2026. "
        "Деньги не вернул."
    )
    assert "неустой" not in context.lower()
    assert runtime.automatic_penalty_candidate(context) is True


def test_does_not_add_penalty_to_unrelated_non_money_case():
    context = "Истец просит признать право собственности на квартиру. Денежного требования нет."
    assert runtime.automatic_penalty_candidate(context) is False


def test_automatic_article_353_calculation_updates_claim_price_and_state_duty():
    context = (
        "Истец: Иванов Иван Иванович, ИИН 900101300001\n"
        "Ответчик: Петров Петр Петрович\n"
        "По договору займа ответчик получил 1 000 000 тенге и обязан вернуть деньги не позднее 10.01.2026. "
        "Деньги не вернул."
    )
    draft = _draft()

    late._apply_verified_penalty(
        context,
        _research(),
        draft,
        filing_date=date(2026, 1, 20),
    )

    assert "статье 353" in draft.late_interest.lower() or "базов" in draft.late_interest.lower()
    assert any("неустой" in item.lower() and parse_amount_kzt(item) for item in draft.requests)
    assert parse_amount_kzt(draft.price_of_claim) > 1_000_000
    assert draft.state_duty
    assert NEEDS_CALCULATION_MARKER not in draft.state_duty


def test_missing_due_date_becomes_local_clarification_not_document_blocker():
    context = (
        "Истец: Иванов Иван Иванович, ИИН 900101300001\n"
        "Ответчик: Петров Петр Петрович\n"
        "По договору займа ответчик получил 1 000 000 тенге. Деньги не вернул."
    )
    draft = _draft(verification_notes=["Неустойка требует проверки: не указана дата просрочки."])

    late._apply_verified_penalty(
        context,
        _research(),
        draft,
        filing_date=date(2026, 1, 20),
    )

    assert draft.status == VerificationStatus.VERIFIED
    assert "Требует уточнения" in draft.late_interest
    assert "дат" in draft.late_interest.lower()
    assert not any("неустой" in item.lower() for item in draft.requests)
    assert draft.verification_notes == []
    assert parse_amount_kzt(draft.price_of_claim) == 1_000_000
    assert NEEDS_CALCULATION_MARKER not in draft.state_duty


def test_research_prompt_checks_penalty_in_same_source_bound_pass():
    context = (
        "Истец: Иванов Иван Иванович, ИИН 900101300001\n"
        "По договору поставки перечислено 2 000 000 тенге. Поставщик должен был вернуть деньги, но не вернул."
    )
    prompt = runtime._research_prompt(context, max_chars=10000, checked_on="2026-09-04")
    assert "Пользователь не обязан знать термин 'неустойка'" in prompt
    assert "В ЭТОМ ЖЕ source-bound проходе" in prompt
    assert "Госпошлину и арифметику не считай моделью" in prompt


def test_optional_penalty_risk_does_not_downgrade_otherwise_verified_research(monkeypatch):
    async def fake_research(_self, _context: str, language: str = "ru") -> LegalResearch:
        return _research(unverified=["Неустойка по статье 353 требует уточнения даты начала просрочки."])

    monkeypatch.setattr(runtime, "_ORIGINAL_FAST_RESEARCH", fake_research)
    result = asyncio.run(
        runtime._research_case(
            object(),
            "По договору займа передано 1 000 000 тенге. Ответчик деньги не вернул.",
            language="ru",
        )
    )
    assert result.unverified_claims == []
    assert result.status == VerificationStatus.VERIFIED


def test_non_penalty_research_problem_is_not_hidden(monkeypatch):
    async def fake_research(_self, _context: str, language: str = "ru") -> LegalResearch:
        return _research(
            unverified=[
                "Неустойка по статье 353 требует уточнения.",
                "Не подтверждено материально-правовое основание основного долга.",
            ]
        )

    monkeypatch.setattr(runtime, "_ORIGINAL_FAST_RESEARCH", fake_research)
    result = asyncio.run(
        runtime._research_case(
            object(),
            "По договору займа передано 1 000 000 тенге. Ответчик деньги не вернул.",
            language="ru",
        )
    )
    assert result.unverified_claims == ["Не подтверждено материально-правовое основание основного долга."]
    assert result.status == VerificationStatus.NEEDS_VERIFICATION
