from __future__ import annotations

import asyncio
import contextlib
from typing import Any

# v2 owns the HTTP contract, encrypted Mini App state, upload handling and
# document-release metadata. v3 replaces only the legal service chain with the
# exact chain used by strict_bot.main(), then adds a parity probe.
from korgan import miniapp_api_v2 as core
from korgan.claim_pipeline_v2 import ClaimPipelineV2Adapter, claim_pipeline_v2_mode
from korgan.claim_service_mux import ClaimServiceMux
from korgan.legal.corpus_refresh import start_corpus_refresh_task
from korgan.pretrial_response import PretrialResponseProductionService
from korgan.token_budget_guard import apply_token_budget_guard

settings = core.settings
apply_token_budget_guard(settings)

# Keep this construction identical to korgan.strict_bot.main(). Claim research
# and drafting go through FinalizedProductionClaimService via ClaimServiceMux;
# consultations/contracts/responses/pretrial documents stay on the broad stable
# production service. ClaimPipelineV2Adapter remains the outer production layer.
stable_service = PretrialResponseProductionService(settings)
claim_mux = ClaimServiceMux(stable_service, settings)
service = ClaimPipelineV2Adapter(claim_mux)
core.service = service

app = core.app
app.title = "KORGAN Mini App API — production legal parity"
app.version = "0.8.0"
_corpus_task: asyncio.Task[None] | None = None


@app.on_event("startup")
async def _production_parity_startup() -> None:
    global _corpus_task
    # strict_bot starts the same official-source corpus refresh loop. It is
    # intentionally non-blocking and preserves the existing corpus on failure.
    if _corpus_task is None:
        _corpus_task = start_corpus_refresh_task()


@app.on_event("shutdown")
async def _production_parity_shutdown() -> None:
    global _corpus_task
    if _corpus_task is not None:
        _corpus_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _corpus_task
        _corpus_task = None


@app.get("/miniapp/parity")
async def parity() -> dict[str, Any]:
    inner = getattr(service, "inner", None)
    stable = getattr(inner, "stable", None)
    return {
        "status": "ok",
        "api_version": "0.8.0",
        "legal_runtime": "strict_bot",
        "service_outer": type(service).__name__,
        "service_claim_mux": type(inner).__name__ if inner is not None else "",
        "service_stable": type(stable).__name__ if stable is not None else "",
        "claim_pipeline_v2_mode": claim_pipeline_v2_mode(),
        "word_quality_target": "10/10",
        "preliminary_fallback": True,
        "official_corpus_refresh": bool(_corpus_task is not None),
        "document_types": sorted(core._DOCUMENT_TYPES),
    }
