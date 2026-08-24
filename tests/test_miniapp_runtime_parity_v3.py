from __future__ import annotations

from fastapi.testclient import TestClient

from korgan import miniapp_api_v3
from korgan.claim_pipeline_v2 import ClaimPipelineV2Adapter
from korgan.claim_service_mux import ClaimServiceMux
from korgan.pretrial_response import PretrialResponseProductionService


def test_miniapp_uses_exact_strict_bot_service_chain() -> None:
    service = miniapp_api_v3.service
    assert isinstance(service, ClaimPipelineV2Adapter)
    assert isinstance(service.inner, ClaimServiceMux)
    assert isinstance(service.inner.stable, PretrialResponseProductionService)
    assert miniapp_api_v3.core.service is service


def test_parity_probe_exposes_required_production_capabilities() -> None:
    with TestClient(miniapp_api_v3.app) as client:
        payload = client.get('/miniapp/parity').json()
    assert payload['status'] == 'ok'
    assert payload['api_version'] == '0.8.0'
    assert payload['legal_runtime'] == 'strict_bot'
    assert payload['service_outer'] == 'ClaimPipelineV2Adapter'
    assert payload['service_claim_mux'] == 'ClaimServiceMux'
    assert payload['service_stable'] == 'PretrialResponseProductionService'
    assert payload['word_quality_target'] == '10/10'
    assert payload['preliminary_fallback'] is True
    assert set(payload['document_types']) == {
        'claim', 'contract', 'response', 'pretrial', 'pretrial_response'
    }
