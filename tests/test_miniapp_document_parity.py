from __future__ import annotations

from korgan.claim_docx import build_claim_docx
from korgan.contract_docx import build_contract_docx
from korgan.pretrial import PretrialProductionService, build_pretrial_docx
from korgan.pretrial_response import PretrialResponseProductionService, build_pretrial_response_docx
from korgan.response_docx import build_response_to_claim_docx


def test_production_service_exposes_all_miniapp_document_methods() -> None:
    required = {
        "research_case",
        "draft_claim",
        "research_contract",
        "draft_contract",
        "research_response_to_claim",
        "draft_response_to_claim",
        "research_pretrial",
        "draft_pretrial",
        "research_pretrial_response",
        "draft_pretrial_response",
    }
    missing = [name for name in sorted(required) if not callable(getattr(PretrialResponseProductionService, name, None))]
    assert missing == []


def test_pretrial_response_service_keeps_pretrial_inheritance() -> None:
    assert issubclass(PretrialResponseProductionService, PretrialProductionService)


def test_all_five_word_renderers_are_callable() -> None:
    for renderer in (
        build_claim_docx,
        build_contract_docx,
        build_response_to_claim_docx,
        build_pretrial_docx,
        build_pretrial_response_docx,
    ):
        assert callable(renderer)
