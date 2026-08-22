from __future__ import annotations

import asyncio
from types import SimpleNamespace

from korgan.claim_pipeline_v2 import ClaimPipelineV2Adapter
from korgan.contract_generation_hotfix import ProductionOpenAILegalService as ContractHotfixService
from korgan.contract_repair_state import (
    contract_repair_completed,
    mark_contract_repair_completed,
    reset_contract_repair_state,
)
from korgan.instant_claim_runtime import InstantClaimProductionService
from korgan.legal_types import ContractDraft, LegalResearch, VerificationStatus
from korgan.pretrial_response import PretrialResponseProductionService
from korgan.universal_quality_service import UniversalQualityProductionService


def _research() -> LegalResearch:
    return LegalResearch(
        status=VerificationStatus.VERIFIED,
        applicable_law=[],
        procedural_requirements=[],
        verified_claims=["Договорная конструкция подтверждена действующим правом."],
        unverified_claims=[],
        source_urls=["https://adilet.zan.kz/rus/docs/example"],
        notes=[],
    )


def _incomplete_contract() -> ContractDraft:
    return ContractDraft(
        status=VerificationStatus.VERIFIED,
        contract_type="договор оказания услуг",
        title="ДОГОВОР ОКАЗАНИЯ УСЛУГ",
        place_and_date="г. Алматы, 22.08.2026",
        party_a=["ТОО «Заказчик», БИН 150640012233"],
        party_b=["ТОО «Исполнитель», БИН 150640012244"],
        preamble=[],
        sections=[],
        requisites_a=["ТОО «Заказчик», БИН 150640012233"],
        requisites_b=["ТОО «Исполнитель», БИН 150640012244"],
        verification_notes=[],
        source_urls=[],
    )


def _contract_payload() -> dict:
    return {
        "contract_type": "договор оказания услуг",
        "title": "ДОГОВОР ОКАЗАНИЯ УСЛУГ",
        "place_and_date": "г. Алматы, 22.08.2026",
        "party_a": ["ТОО «Заказчик», БИН 150640012233"],
        "party_b": ["ТОО «Исполнитель», БИН 150640012244"],
        "preamble": [],
        "sections": [],
        "requisites_a": ["ТОО «Заказчик», БИН 150640012233"],
        "requisites_b": ["ТОО «Исполнитель», БИН 150640012244"],
        "verification_notes": [],
    }


def _production_adapter() -> ClaimPipelineV2Adapter:
    inner = object.__new__(PretrialResponseProductionService)
    inner.settings = SimpleNamespace(max_case_text_chars=42000)
    return ClaimPipelineV2Adapter(inner)


def test_outer_repair_is_skipped_only_after_lower_repair_completed(monkeypatch):
    draft = _incomplete_contract()
    calls = {"lower": 0, "outer_repair": 0}

    async def lower_contract(self, case_context, research, language="ru"):
        calls["lower"] += 1
        mark_contract_repair_completed()
        return draft

    async def forbidden_outer_repair(self, **kwargs):
        calls["outer_repair"] += 1
        raise AssertionError("a second contract repair must not run")

    monkeypatch.setattr(InstantClaimProductionService, "draft_contract", lower_contract)
    monkeypatch.setattr(UniversalQualityProductionService, "_quality_repair", forbidden_outer_repair)

    adapter = _production_adapter()
    result = asyncio.run(
        adapter.draft_contract(
            "Стороны: ТОО «Заказчик», БИН 150640012233; ТОО «Исполнитель», БИН 150640012244",
            _research(),
            language="ru",
        )
    )

    assert result is draft
    assert calls == {"lower": 1, "outer_repair": 0}
    assert result.status == VerificationStatus.NEEDS_VERIFICATION
    assert any("KORGAN QUALITY" in note for note in result.verification_notes)


def test_outer_repair_is_preserved_when_lower_pipeline_did_not_repair(monkeypatch):
    draft = _incomplete_contract()
    calls = {"lower": 0, "outer_repair": 0}

    async def lower_contract(self, case_context, research, language="ru"):
        calls["lower"] += 1
        return draft

    async def outer_repair(self, **kwargs):
        calls["outer_repair"] += 1
        return _contract_payload()

    monkeypatch.setattr(InstantClaimProductionService, "draft_contract", lower_contract)
    monkeypatch.setattr(UniversalQualityProductionService, "_quality_repair", outer_repair)

    adapter = _production_adapter()
    result = asyncio.run(
        adapter.draft_contract(
            "Стороны: ТОО «Заказчик», БИН 150640012233; ТОО «Исполнитель», БИН 150640012244",
            _research(),
            language="ru",
        )
    )

    assert calls == {"lower": 1, "outer_repair": 1}
    assert result.status == VerificationStatus.NEEDS_VERIFICATION


def test_contract_hotfix_marks_successful_lower_repair(monkeypatch):
    class FakeResponses:
        async def create(self, **kwargs):
            return SimpleNamespace(
                output_text="{}",
                status="completed",
                incomplete_details=None,
                output=[],
            )

    service = object.__new__(ContractHotfixService)
    service.client = SimpleNamespace(responses=FakeResponses())
    monkeypatch.setattr(ContractHotfixService, "_json_schema", lambda self, name, schema: {})

    async def exercise() -> bool:
        reset_contract_repair_state()
        assert contract_repair_completed() is False
        await service._structured_response(
            model="gpt-5.1",
            instructions="repair",
            content="{}",
            schema_name="korgan_contract_repair",
            schema={},
        )
        return contract_repair_completed()

    assert asyncio.run(exercise()) is True


def test_production_service_mro_and_adapter_expose_quality_contract_path():
    mro = PretrialResponseProductionService.mro()
    assert UniversalQualityProductionService in mro
    assert ContractHotfixService in mro
    assert mro.index(UniversalQualityProductionService) < mro.index(ContractHotfixService)

    adapter = _production_adapter()
    assert adapter.draft_contract.__func__ is UniversalQualityProductionService.draft_contract
