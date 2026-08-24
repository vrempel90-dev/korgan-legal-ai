from __future__ import annotations

import pytest

from korgan.pretrial_response import PretrialResponseProductionService
from korgan.professional_consultation_guard import install_professional_consultation_guard


DOCUMENT_METHODS = (
    "draft_claim",
    "draft_contract",
    "draft_pretrial",
    "draft_pretrial_response",
)


@pytest.mark.parametrize("method_name", DOCUMENT_METHODS)
def test_consult_guard_does_not_replace_document_generators(method_name: str) -> None:
    before = getattr(PretrialResponseProductionService, method_name)

    install_professional_consultation_guard()

    after = getattr(PretrialResponseProductionService, method_name)
    assert after is before


def test_consult_guard_changes_only_consultation_route() -> None:
    install_professional_consultation_guard()

    assert PretrialResponseProductionService.consult.__module__ == "korgan.professional_consultation_guard"
    for method_name in DOCUMENT_METHODS:
        assert getattr(PretrialResponseProductionService, method_name).__module__ != "korgan.professional_consultation_guard"
