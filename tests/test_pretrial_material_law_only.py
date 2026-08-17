from __future__ import annotations

from korgan.legal_types import LegalResearch, VerificationStatus
from korgan.pretrial import (
    PretrialDraft,
    PretrialProductionService,
    is_material_law_line,
    is_pretrial_request,
    pretrial_release_blockers,
    prioritize_material_basis,
)
from korgan.response_legal import ProductionOpenAILegalService


def _research(*verified: str) -> LegalResearch:
    return LegalResearch(
        status=VerificationStatus.VERIFIED,
        applicable_law=[],
        procedural_requirements=[],
        verified_claims=list(verified),
        unverified_claims=[],
        source_urls=["https://adilet.zan.kz/rus/docs/K940001000_"],
        notes=[],
    )


def _draft(legal_basis: list[str]) -> PretrialDraft:
    return PretrialDraft(
        status=VerificationStatus.VERIFIED,
        title="ДОСУДЕБНАЯ ПРЕТЕНЗИЯ",
        sender=["ТОО Истец"],
        recipient=["ТОО Ответчик"],
        facts=["По договору возникла задолженность 1 000 000 тенге."],
        legal_basis=legal_basis,
        demands=["Погасить основную задолженность 1 000 000 тенге."],
        deadline="",
        consequences=["При неисполнении заявитель вправе использовать предусмотренные законом способы защиты."],
        attachments=[],
    )


def test_pretrial_intent_does_not_steal_advice_questions() -> None:
    assert is_pretrial_request("Подготовь досудебную претензию о взыскании долга")
    assert is_pretrial_request("Сотқа дейінгі талапты дайында")
    assert not is_pretrial_request("Как подготовить досудебную претензию?")
    assert not is_pretrial_request("Сотқа дейінгі талапты қалай дайындауға болады?")


def test_gpk_representative_costs_are_not_main_debt_material_law() -> None:
    line = (
        "Расходы представителя могут возмещаться. Правовое основание: статья 113 ГПК РК."
    )
    assert not is_material_law_line(line)


def test_civil_code_obligation_is_material_law() -> None:
    line = "Обязательство должно исполняться надлежащим образом. Правовое основание: статья 272 ГК РК."
    assert is_material_law_line(line)


def test_material_basis_is_forced_before_gpk_costs() -> None:
    material = (
        "Обязательство должно исполняться надлежащим образом "
        "[основание: статья 272 ГК РК; текст нормы: обязательство должно исполняться надлежащим образом; "
        "источник: https://adilet.zan.kz/rus/docs/K940001000_]"
    )
    current = ["Расходы представителя. Правовое основание: статья 113 ГПК РК."]
    result = prioritize_material_basis(current, _research(material))
    assert "статья 272 ГК РК" in result[0]
    assert "статья 113 ГПК РК" in result[-1]


def test_pretrial_with_only_gpk_is_blocked_for_principal_debt() -> None:
    gpk = (
        "Расходы представителя возмещаются "
        "[основание: статья 113 ГПК РК; текст нормы: расходы по оплате помощи представителя; "
        "источник: https://adilet.zan.kz/rus/docs/K1500000377]"
    )
    blockers = pretrial_release_blockers(
        _draft(["Расходы представителя. Правовое основание: статья 113 ГПК РК."]),
        _research(gpk),
        "Взыскать задолженность по договору 1 000 000 тенге",
    )
    assert any("материально-правовой" in item.lower() for item in blockers)


def test_pretrial_with_verified_material_basis_is_not_blocked_as_procedural_only() -> None:
    material = (
        "Обязательство должно исполняться надлежащим образом "
        "[основание: статья 272 ГК РК; текст нормы: обязательство должно исполняться надлежащим образом; "
        "источник: https://adilet.zan.kz/rus/docs/K940001000_]"
    )
    blockers = pretrial_release_blockers(
        _draft(["Обязательство должно исполняться надлежащим образом. Правовое основание: статья 272 ГК РК."]),
        _research(material),
        "Взыскать задолженность по договору 1 000 000 тенге",
    )
    assert not any("материально-правовой" in item.lower() for item in blockers)


def test_claim_methods_are_not_overridden_by_pretrial_service() -> None:
    assert "draft_claim" not in PretrialProductionService.__dict__
    assert "research_case" not in PretrialProductionService.__dict__
    assert PretrialProductionService.draft_claim is ProductionOpenAILegalService.draft_claim
    assert PretrialProductionService.research_case is ProductionOpenAILegalService.research_case
