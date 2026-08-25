from __future__ import annotations

import asyncio


def test_safe_installer_enables_only_external_only_repair_skip(monkeypatch):
    from korgan import production_cost_speed_optimizer_safe as safe
    from korgan.legal import corpus_refresh

    calls: list[str] = []

    def keep_refresh(current, _loader):
        return current

    def original_refresh(_path=None):
        return 0

    monkeypatch.setattr(safe, "_INSTALLED", False)
    monkeypatch.setattr(safe.optimizer, "_progressive_refresh_factory", keep_refresh)
    monkeypatch.setattr(safe.optimizer, "_install_research_scope_optimizer", lambda: calls.append("scope"))
    monkeypatch.setattr(safe.optimizer, "_install_rag_search_context_optimizer", lambda: calls.append("rag"))
    monkeypatch.setattr(safe, "_install_safe_futile_repair_skip", lambda: calls.append("repair-skip"))
    monkeypatch.setattr(safe.optimizer, "_install_economic_court_registry", lambda: calls.append("court"))
    monkeypatch.setattr(corpus_refresh, "refresh_corpus_once", original_refresh)

    safe.install_production_cost_speed_optimizer_safe()

    assert calls == ["scope", "rag", "repair-skip", "court"]
    assert corpus_refresh.refresh_corpus_once is original_refresh


def test_external_only_classifier_never_skips_substantive_or_mixed_defects():
    from korgan.production_cost_speed_optimizer import _all_issues_external_only

    assert _all_issues_external_only([
        "не определено конкретное наименование суда",
        "не указан адрес ответчика",
        "не указан БИН истца",
    ]) is True

    assert _all_issues_external_only([
        "не указан адрес ответчика",
        "есть правовая ссылка, не прошедшая source-bound/corpus проверку",
    ]) is False

    assert _all_issues_external_only([
        "не определено конкретное наименование суда",
        "требование о неустойке исчезло из ПРОШУ СУД",
    ]) is False


def test_claim_only_skip_delegates_mixed_and_nonclaim_repairs_dynamically():
    from korgan import production_cost_speed_optimizer_safe as safe
    from korgan.fast_professional_litigation import FastProfessionalLitigationService
    from korgan.legal_types import LegalResearch, VerificationStatus
    from korgan.universal_quality_service import UniversalQualityProductionService

    cls = FastProfessionalLitigationService
    original_direct = cls.__dict__.get("_quality_repair")
    original_base = UniversalQualityProductionService._quality_repair
    delegated: list[str] = []

    async def dynamic_delegate(self, **kwargs):
        delegated.append(str(kwargs["schema_name"]))
        return {"delegated": str(kwargs["schema_name"])}

    research = LegalResearch(
        status=VerificationStatus.VERIFIED,
        applicable_law=[],
        procedural_requirements=[],
        verified_claims=[],
        unverified_claims=[],
        source_urls=[],
        notes=[],
    )
    payload = {"title": "unchanged"}

    async def call(schema_name: str, issues: list[str]):
        service = object.__new__(cls)
        return await service._quality_repair(
            schema_name=schema_name,
            schema={},
            case_context="case",
            research=research,
            current_payload=payload,
            issues=issues,
            language="ru",
            document_label="document",
            extra_rules="",
        )

    try:
        if "_quality_repair" in cls.__dict__:
            delattr(cls, "_quality_repair")
        UniversalQualityProductionService._quality_repair = dynamic_delegate
        safe._install_safe_futile_repair_skip()

        skipped = asyncio.run(call(
            "korgan_fast_professional_repair",
            ["не указан адрес ответчика", "не определено конкретное наименование суда"],
        ))
        assert skipped == payload
        assert skipped is not payload
        assert delegated == []

        mixed = asyncio.run(call(
            "korgan_fast_professional_repair",
            ["не указан адрес ответчика", "есть правовая ссылка, не прошедшая source-bound/corpus проверку"],
        ))
        assert mixed == {"delegated": "korgan_fast_professional_repair"}
        assert delegated == ["korgan_fast_professional_repair"]

        contract = asyncio.run(call(
            "korgan_universal_quality_contract",
            ["не указан адрес стороны"],
        ))
        assert contract == {"delegated": "korgan_universal_quality_contract"}
        assert delegated == [
            "korgan_fast_professional_repair",
            "korgan_universal_quality_contract",
        ]
    finally:
        UniversalQualityProductionService._quality_repair = original_base
        if "_quality_repair" in cls.__dict__:
            delattr(cls, "_quality_repair")
        if original_direct is not None:
            cls._quality_repair = original_direct
