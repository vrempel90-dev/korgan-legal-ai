from __future__ import annotations

from korgan.legal_types import LegalResearch, VerificationStatus
from korgan.material_law_guard import (
    has_material_basis,
    has_material_verified,
    inject_material_basis,
    is_material_law_line,
    material_research_context,
    requires_material_law,
)


def _research(*verified: str) -> LegalResearch:
    return LegalResearch(
        status=VerificationStatus.VERIFIED,
        applicable_law=[],
        procedural_requirements=[],
        verified_claims=list(verified),
        unverified_claims=[],
        source_urls=["https://adilet.zan.kz/rus/docs/K990000409_"],
        notes=[],
    )


def test_representative_cost_rule_is_not_material_law() -> None:
    line = (
        "Расходы представителя возмещаются в установленных пределах "
        "[основание: статья 113 ГПК РК; текст нормы: «суд присуждает расходы представителя»; "
        "источник: https://adilet.zan.kz/rus/docs/K1500000377]"
    )
    assert not is_material_law_line(line)


def test_civil_code_obligation_rule_is_material_law() -> None:
    line = (
        "Должник обязан исполнить денежное обязательство "
        "[основание: статья 272 ГК РК; текст нормы: «обязательство должно исполняться надлежащим образом»; "
        "источник: https://adilet.zan.kz/rus/docs/K940001000_]"
    )
    assert is_material_law_line(line)


def test_substantive_debt_requires_material_law() -> None:
    assert requires_material_law("Взыскать задолженность по договору в размере 4 025 000 тенге")


def test_material_basis_is_injected_before_procedure() -> None:
    material = (
        "Обязательство должно исполняться надлежащим образом "
        "[основание: статья 272 ГК РК; текст нормы: «обязательство должно исполняться надлежащим образом»; "
        "источник: https://adilet.zan.kz/rus/docs/K940001000_]"
    )
    research = _research(material)
    procedural = ["Расходы представителя. Правовое основание: статья 113 ГПК РК."]
    result = inject_material_basis(procedural, research)
    assert result[0].startswith("Обязательство должно исполняться надлежащим образом")
    assert "статья 272 ГК РК" in result[0]
    assert result[-1] == procedural[0]
    assert has_material_basis(result)
    assert has_material_verified(research)


def test_existing_material_basis_is_not_duplicated() -> None:
    existing = ["Обязательство должно исполняться надлежащим образом. Правовое основание: статья 272 ГК РК."]
    result = inject_material_basis(existing, _research())
    assert result == existing


def test_research_context_marks_instruction_as_not_case_fact() -> None:
    value = material_research_context("Факт дела", "досудебной претензии")
    assert "НЕ ФАКТ ДЕЛА" in value
    assert "ГПК" in value
    assert "НЕ считаются правовой опорой" in value
