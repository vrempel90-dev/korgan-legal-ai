from __future__ import annotations

import asyncio

from korgan.additive_legal_guard import AdditiveLegalGuardService
from korgan.legal_types import LegalResearch, VerificationStatus
from korgan.pretrial_only_material_guard import PretrialOnlyMaterialGuardService
from korgan.stable_legal_release import StableLegalProductionService


def _research() -> LegalResearch:
    return LegalResearch(
        status=VerificationStatus.VERIFIED,
        applicable_law=[],
        procedural_requirements=[],
        verified_claims=[
            "Расходы представителя могут быть взысканы. "
            "[основание: статья 113 ГПК РК; текст нормы: «расходы представителя»; "
            "источник: https://adilet.zan.kz/rus/docs/K1500000377]"
        ],
        unverified_claims=[],
        source_urls=["https://adilet.zan.kz/rus/docs/K1500000377"],
        notes=[],
    )


def test_claim_research_does_not_run_client_material_law_second_pass(monkeypatch) -> None:
    calls: list[str] = []

    async def fake_research_case(self, case_context: str, language: str = "ru") -> LegalResearch:
        calls.append(case_context)
        return _research()

    monkeypatch.setattr(StableLegalProductionService, "research_case", fake_research_case)
    service = object.__new__(PretrialOnlyMaterialGuardService)

    research = asyncio.run(
        service.research_case(
            "Взыскать задолженность по договору 4 025 000 тенге",
            language="ru",
        )
    )

    assert len(calls) == 1
    assert research.verified_claims
    assert not research.unverified_claims


def test_pretrial_keeps_material_law_second_pass(monkeypatch) -> None:
    calls: list[str] = []

    async def fake_research_case(self, case_context: str, language: str = "ru") -> LegalResearch:
        calls.append(case_context)
        return _research()

    monkeypatch.setattr(StableLegalProductionService, "research_case", fake_research_case)
    service = object.__new__(PretrialOnlyMaterialGuardService)

    research = asyncio.run(
        service.research_pretrial(
            "Подготовить досудебную претензию о взыскании задолженности по договору 4 025 000 тенге",
            language="ru",
        )
    )

    assert len(calls) == 2
    assert "НЕ ФАКТ ДЕЛА" in calls[1]
    assert any("материально-прав" in item.lower() for item in research.unverified_claims)


def test_pretrial_only_service_keeps_pretrial_draft_guard() -> None:
    assert PretrialOnlyMaterialGuardService.draft_pretrial is AdditiveLegalGuardService.draft_pretrial
