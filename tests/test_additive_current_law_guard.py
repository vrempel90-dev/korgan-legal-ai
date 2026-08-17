from __future__ import annotations

from datetime import date

from korgan.additive_legal_guard import (
    AdditiveLegalGuardService,
    _pretrial_basis_coverage,
    _response_basis_coverage,
)
from korgan.legal.current_law_guard import (
    adilet_document_id,
    is_current_source,
    replacement_for,
)
from korgan.legal.rk_catalog import ACT_BY_ID
from korgan.legal_types import LegalResearch, VerificationStatus
from korgan.pretrial import PretrialDraft, PretrialProductionService
from korgan.response_types import ResponseObjection, ResponseToClaimDraft


def _research(*verified: str) -> LegalResearch:
    return LegalResearch(
        status=VerificationStatus.VERIFIED,
        applicable_law=[],
        procedural_requirements=[],
        verified_claims=list(verified),
        unverified_claims=[],
        source_urls=[],
        notes=[],
    )


def test_current_catalog_uses_2026_replacements() -> None:
    assert ACT_BY_ID["CONSTITUTION_RK"].adilet_id == "K2600000000"
    assert ACT_BY_ID["BANKS_RK"].adilet_id == "Z2600000258"
    assert ACT_BY_ID["PUBLIC_SERVICE_RK"].adilet_id == "Z2600000290"


def test_old_constitution_is_rejected_after_july_2026() -> None:
    old = "https://adilet.zan.kz/rus/docs/K950001000_"
    new = "https://adilet.zan.kz/rus/docs/K2600000000"
    assert is_current_source(old, on_date=date(2026, 6, 30))
    assert not is_current_source(old, on_date=date(2026, 7, 1))
    assert is_current_source(new, on_date=date(2026, 8, 17))
    assert replacement_for(old, on_date=date(2026, 8, 17)) == "K2600000000"


def test_old_civil_service_law_is_rejected_after_july_2026() -> None:
    old = "https://www.adilet.zan.kz/rus/docs/Z1500000416"
    assert not is_current_source(old, on_date=date(2026, 8, 17))
    assert replacement_for(old, on_date=date(2026, 8, 17)) == "Z2600000290"


def test_old_bank_law_only_allows_explicit_transition_articles() -> None:
    old = "https://adilet.zan.kz/rus/docs/Z950002444_"
    current = "https://adilet.zan.kz/rus/docs/Z2600000258"
    on_date = date(2026, 8, 17)

    assert not is_current_source(old, article_label="статья 2 Закона о банках", on_date=on_date)
    assert is_current_source(old, article_label="статья 40-1 Закона о банках", on_date=on_date)
    assert is_current_source(old, article_label="пункт 7-2 статьи 50 Закона о банках", on_date=on_date)
    assert not is_current_source(old, article_label="пункт 4 статьи 50 Закона о банках", on_date=on_date)
    assert is_current_source(current, article_label="статья 2 Закона о банках", on_date=on_date)
    assert not is_current_source(old, article_label="статья 40-1", on_date=date(2027, 1, 1))


def test_adilet_document_id_is_strict() -> None:
    assert adilet_document_id("https://adilet.zan.kz/rus/docs/Z2600000258#z2") == "Z2600000258"
    assert adilet_document_id("https://example.com/rus/docs/Z2600000258") == ""


def test_pretrial_demand_without_own_verified_basis_is_blocked() -> None:
    draft = PretrialDraft(
        status=VerificationStatus.VERIFIED,
        title="Досудебная претензия",
        sender=["Иванов"],
        recipient=["ТОО Ромашка"],
        facts=["Заработная плата не выплачена."],
        legal_basis=[],
        demands=["Выплатить задолженность по заработной плате 420 000 тенге."],
        deadline="",
        consequences=[],
        attachments=[],
    )

    missing = _pretrial_basis_coverage("Работодатель не выплатил зарплату", draft, _research())

    assert missing == ["взыскание заработной платы"]
    assert draft.status == VerificationStatus.NEEDS_VERIFICATION


def test_pretrial_restores_matching_verified_basis_without_inventing_article() -> None:
    verified = (
        "Работодатель обязан выплачивать заработную плату. "
        "[основание: статья 113 ТК РК; текст нормы: «Заработная плата выплачивается работнику»; "
        "источник: https://adilet.zan.kz/rus/docs/K1500000414]"
    )
    research = _research(verified)
    draft = PretrialDraft(
        status=VerificationStatus.VERIFIED,
        title="Досудебная претензия",
        sender=["Иванов"],
        recipient=["ТОО Ромашка"],
        facts=["Заработная плата не выплачена."],
        legal_basis=[],
        demands=["Выплатить задолженность по заработной плате 420 000 тенге."],
        deadline="",
        consequences=[],
        attachments=[],
    )

    assert _pretrial_basis_coverage("Работодатель не выплатил зарплату", draft, research) == []
    assert any("статья 113 ТК РК" in line for line in draft.legal_basis)


def test_substantive_response_cannot_rely_only_on_article_166() -> None:
    research = _research(
        "Ответчик вправе представить отзыв на иск. "
        "[основание: статья 166 ГПК РК; текст нормы: «Ответчик представляет отзыв»; "
        "источник: https://adilet.zan.kz/rus/docs/K1500000377]"
    )
    draft = ResponseToClaimDraft(
        status=VerificationStatus.VERIFIED,
        objections=[ResponseObjection(text="Задолженность по договору займа отсутствует, поскольку сумма возвращена.")],
        legal_basis=["Правовое основание: статья 166 ГПК РК."],
    )

    issues = _response_basis_coverage(draft, research)

    assert issues
    assert draft.status == VerificationStatus.NEEDS_VERIFICATION


def test_substantive_response_accepts_separate_verified_material_law() -> None:
    research = _research(
        "Ответчик вправе представить отзыв на иск. "
        "[основание: статья 166 ГПК РК; текст нормы: «Ответчик представляет отзыв»; "
        "источник: https://adilet.zan.kz/rus/docs/K1500000377]",
        "Заемщик обязан возвратить сумму займа в предусмотренном договором порядке. "
        "[основание: статья 722 ГК РК; текст нормы: «Заемщик обязан возвратить предмет займа»; "
        "источник: https://adilet.zan.kz/rus/docs/K990000409_]",
    )
    draft = ResponseToClaimDraft(
        status=VerificationStatus.VERIFIED,
        objections=[ResponseObjection(text="Спор касается задолженности по договору займа и ее возврата.")],
        legal_basis=["Правовое основание: статья 722 ГК РК."],
    )

    assert _response_basis_coverage(draft, research) == []
    assert draft.status == VerificationStatus.VERIFIED


def test_additive_service_does_not_override_existing_claim_or_contract_methods() -> None:
    # The new class adds only pre-trial/response post-checks.  Claim and contract
    # generation continue through the already deployed inherited implementation.
    assert "draft_claim" not in AdditiveLegalGuardService.__dict__
    assert "draft_contract" not in AdditiveLegalGuardService.__dict__
    assert issubclass(AdditiveLegalGuardService, PretrialProductionService)
