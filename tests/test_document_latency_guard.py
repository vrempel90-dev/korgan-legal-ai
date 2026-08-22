from __future__ import annotations

import asyncio
from types import SimpleNamespace

import korgan.contract_generation_hotfix as contract_hotfix
from korgan.claim_pipeline_v2 import ClaimPipelineV2Adapter
from korgan.contract_generation_hotfix import ProductionOpenAILegalService as ContractHotfixService
from korgan.contract_repair_state import (
    contract_repair_attempted,
    contract_repair_completed,
    mark_contract_repair_attempted,
    mark_contract_repair_completed,
    reset_contract_repair_state,
)
from korgan.instant_claim_runtime import InstantClaimProductionService
from korgan.legal_types import ContractDraft, LegalResearch, VerificationStatus
from korgan.pretrial_response import PretrialResponseProductionService
from korgan.universal_quality_service import UniversalQualityProductionService


def _research() -> LegalResearch:
    """Return a tiny source-bound research object suitable for latency routing tests."""
    return LegalResearch(
        status=VerificationStatus.VERIFIED,
        applicable_law=[],
        procedural_requirements=[],
        verified_claims=["Договорная конструкция подтверждена действующим правом."],
        unverified_claims=[],
        source_urls=["https://adilet.zan.kz/rus/docs/example"],
        notes=[],
    )


def _incomplete_contract(label: str = "A") -> ContractDraft:
    """Return a deliberately low-quality contract that must never be upgraded silently."""
    return ContractDraft.from_payload(
        status=VerificationStatus.VERIFIED,
        source_urls=[],
        payload={
            "contract_type": "договор оказания услуг",
            "title": f"ДОГОВОР {label}",
            "place_and_date": "Алматы, 22.08.2026",
            "party_a": [f"Заказчик {label}"],
            "party_b": [f"Исполнитель {label}"],
            "preamble": [],
            "sections": [],
            "requisites_a": [f"Заказчик {label}"],
            "requisites_b": [f"Исполнитель {label}"],
            "verification_notes": [],
        },
    )


def _complete_contract_payload(label: str = "A") -> dict:
    """Return a structurally complete payload representative of a repaired contract."""
    return {
        "contract_type": "договор оказания услуг",
        "title": f"ДОГОВОР {label}",
        "place_and_date": "Алматы, 22.08.2026",
        "party_a": [f"Заказчик {label}"],
        "party_b": [f"Исполнитель {label}"],
        "preamble": [
            f"Заказчик {label}, именуемый в дальнейшем «Заказчик», в лице директора, действующего на основании устава, "
            f"и Исполнитель {label}, именуемый в дальнейшем «Исполнитель», в лице директора, действующего на основании устава, "
            "заключили настоящий Договор о нижеследующем."
        ],
        "sections": [
            {
                "heading": "Предмет договора",
                "clauses": [
                    {"text": "Исполнитель оказывает услуги в согласованном объёме.", "subclauses": []},
                    {"text": "Заказчик принимает результат оказанных услуг.", "subclauses": []},
                    {"text": "Стороны согласуют порядок исполнения письменно.", "subclauses": []},
                    {"text": "Приёмка подтверждается документами сторон.", "subclauses": []},
                    {"text": "Обязательства прекращаются после полного исполнения.", "subclauses": []},
                ],
            }
        ],
        "requisites_a": [f"Заказчик {label}"],
        "requisites_b": [f"Исполнитель {label}"],
        "verification_notes": [],
    }


def _production_adapter() -> ClaimPipelineV2Adapter:
    """Build the same adapter/service boundary used by strict_bot without network clients."""
    inner = object.__new__(PretrialResponseProductionService)
    inner.settings = SimpleNamespace(max_case_text_chars=42000)
    return ClaimPipelineV2Adapter(inner)


def test_outer_repair_is_skipped_only_after_lower_repair_completed(monkeypatch):
    """A completed lower repair must consume the only repair budget for the request."""
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
    result = asyncio.run(adapter.draft_contract("case-a", _research(), language="ru"))

    assert result is draft
    assert calls == {"lower": 1, "outer_repair": 0}
    assert result.status == VerificationStatus.NEEDS_VERIFICATION
    assert any("KORGAN QUALITY" in note for note in result.verification_notes)


def test_outer_repair_is_preserved_when_lower_pipeline_did_not_repair(monkeypatch):
    """Missing-term cases still retain the original outer repair when lower QA did not repair."""
    draft = _incomplete_contract()
    calls = {"lower": 0, "outer_repair": 0}

    async def lower_contract(self, case_context, research, language="ru"):
        calls["lower"] += 1
        return draft

    async def outer_repair(self, **kwargs):
        calls["outer_repair"] += 1
        return _complete_contract_payload()

    monkeypatch.setattr(InstantClaimProductionService, "draft_contract", lower_contract)
    monkeypatch.setattr(UniversalQualityProductionService, "_quality_repair", outer_repair)

    adapter = _production_adapter()
    result = asyncio.run(adapter.draft_contract("case-b", _research(), language="ru"))

    assert calls == {"lower": 1, "outer_repair": 1}
    assert isinstance(result, ContractDraft)


def test_parsed_incomplete_repair_is_not_marked_completed(monkeypatch):
    """JSON parsing alone must never suppress the later outer repair opportunity."""
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

    async def exercise() -> tuple[bool, bool]:
        reset_contract_repair_state()
        await service._structured_response(
            model="gpt-5.1",
            instructions="repair",
            content="{}",
            schema_name="korgan_contract_repair",
            schema={},
        )
        return contract_repair_attempted(), contract_repair_completed()

    attempted, completed = asyncio.run(exercise())
    assert attempted is True
    assert completed is False


def test_full_lower_repair_marks_completed_only_after_lower_pipeline_returns(monkeypatch):
    """Completion is set only after a full ContractDraft survives lower revalidation."""
    calls = {"lower": 0, "revalidation": 0}

    async def full_lower_pipeline(self, case_context, research, language="ru"):
        calls["lower"] += 1
        mark_contract_repair_attempted()
        repaired = ContractDraft.from_payload(
            status=VerificationStatus.VERIFIED,
            source_urls=list(research.source_urls),
            payload=_complete_contract_payload("FULL"),
        )
        calls["revalidation"] += 1
        assert repaired.sections and len(repaired.sections[0].clauses) >= 5
        return repaired

    monkeypatch.setattr(
        contract_hotfix._BaseProductionOpenAILegalService,
        "draft_contract",
        full_lower_pipeline,
    )
    service = object.__new__(ContractHotfixService)

    async def exercise() -> tuple[ContractDraft, bool]:
        reset_contract_repair_state()
        draft = await service.draft_contract("full-case", _research(), language="ru")
        return draft, contract_repair_completed()

    draft, completed = asyncio.run(exercise())
    assert isinstance(draft, ContractDraft)
    assert calls == {"lower": 1, "revalidation": 1}
    assert completed is True


def test_concurrent_contract_requests_keep_repair_state_isolated(monkeypatch):
    """Two overlapping client requests must never share the ContextVar repair budget."""
    entered = 0
    both_entered = asyncio.Event()
    outer_repairs: list[str] = []

    async def lower_contract(self, case_context, research, language="ru"):
        nonlocal entered
        entered += 1
        if entered == 2:
            both_entered.set()
        await both_entered.wait()
        if case_context == "lower-repaired":
            mark_contract_repair_completed()
        await asyncio.sleep(0)
        return _incomplete_contract(case_context)

    async def outer_repair(self, **kwargs):
        outer_repairs.append(str(kwargs["case_context"]))
        await asyncio.sleep(0)
        return _complete_contract_payload(str(kwargs["case_context"]))

    monkeypatch.setattr(InstantClaimProductionService, "draft_contract", lower_contract)
    monkeypatch.setattr(UniversalQualityProductionService, "_quality_repair", outer_repair)

    async def exercise() -> tuple[ContractDraft, ContractDraft]:
        first = _production_adapter()
        second = _production_adapter()
        return tuple(
            await asyncio.gather(
                first.draft_contract("lower-repaired", _research(), language="ru"),
                second.draft_contract("needs-outer-repair", _research(), language="ru"),
            )
        )

    first_result, second_result = asyncio.run(exercise())
    assert outer_repairs == ["needs-outer-repair"]
    assert first_result.status == VerificationStatus.NEEDS_VERIFICATION
    assert isinstance(second_result, ContractDraft)


def test_production_service_mro_and_adapter_expose_quality_contract_path():
    """The strict_bot service/adapter boundary must expose the edited quality method."""
    mro = PretrialResponseProductionService.mro()
    assert UniversalQualityProductionService in mro
    assert ContractHotfixService in mro
    assert mro.index(UniversalQualityProductionService) < mro.index(ContractHotfixService)

    adapter = _production_adapter()
    assert adapter.draft_contract.__func__ is UniversalQualityProductionService.draft_contract
