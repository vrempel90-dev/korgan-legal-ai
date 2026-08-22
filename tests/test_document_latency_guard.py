from __future__ import annotations

import pytest

from korgan.document_latency_guard import _latency_bounded_draft_contract
from korgan.instant_claim_runtime import InstantClaimProductionService
from korgan.legal_types import ContractDraft, LegalResearch, VerificationStatus
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


@pytest.mark.asyncio
async def test_latency_guard_uses_lower_contract_qa_once_and_never_runs_outer_repair(monkeypatch):
    draft = _incomplete_contract()
    calls = {"lower": 0, "outer_repair": 0}

    async def lower_contract(self, case_context, research, language="ru"):
        calls["lower"] += 1
        return draft

    async def forbidden_outer_repair(self, **kwargs):
        calls["outer_repair"] += 1
        raise AssertionError("duplicate outer contract repair must not run")

    monkeypatch.setattr(InstantClaimProductionService, "draft_contract", lower_contract)
    monkeypatch.setattr(UniversalQualityProductionService, "_quality_repair", forbidden_outer_repair)

    service = object.__new__(UniversalQualityProductionService)
    result = await _latency_bounded_draft_contract(
        service,
        "Стороны: ТОО «Заказчик», БИН 150640012233; ТОО «Исполнитель», БИН 150640012244",
        _research(),
        language="ru",
    )

    assert result is draft
    assert calls == {"lower": 1, "outer_repair": 0}
    assert result.status == VerificationStatus.NEEDS_VERIFICATION
    assert any("KORGAN QUALITY" in note for note in result.verification_notes)


def test_latency_guard_is_contract_only():
    assert UniversalQualityProductionService.draft_claim is not _latency_bounded_draft_contract
    assert UniversalQualityProductionService.draft_response_to_claim is not _latency_bounded_draft_contract
