from __future__ import annotations

import asyncio
import contextlib
import os
from typing import Any

# v2 owns the HTTP contract, encrypted Mini App state, upload handling and
# document-release metadata. v3 replaces only the legal service chain with the
# exact chain used by strict_bot.main(), then adds a parity probe.
from korgan import miniapp_api_v2 as core
from korgan.asgi_lifespan import add_lifespan
from korgan.claim_pipeline_v2 import ClaimPipelineV2Adapter, claim_pipeline_v2_mode
from korgan.claim_service_mux import ClaimServiceMux
from korgan.legal.corpus_refresh import start_corpus_refresh_task
from korgan.pretrial_response import PretrialResponseProductionService
from korgan.token_budget_guard import apply_token_budget_guard

PARITY_REVISION = "2026-08-24.2"
settings = core.settings
apply_token_budget_guard(settings)

# Keep this construction identical to korgan.strict_bot.main(). Claim research
# and drafting go through FinalizedProductionClaimService via ClaimServiceMux;
# consultations/contracts/responses/pretrial documents stay on the broad stable
# production service. ClaimPipelineV2Adapter remains the outer production layer.
stable_service = PretrialResponseProductionService(settings)
claim_mux = ClaimServiceMux(stable_service, settings)
service = ClaimPipelineV2Adapter(claim_mux)
# v2 routes claims through ``core.service``, while its legacy helpers resolve
# contract/response/pre-trial methods through ``miniapp_api.service``. Both
# names must point at this exact production chain; otherwise the MiniApp keeps
# two OpenAI clients with configuration that can drift by document type.
core.service = service
core.legacy.service = service

app = core.app
app.title = "KORGAN Mini App API — production legal parity"
app.version = "0.8.0"
_corpus_task: asyncio.Task[None] | None = None


async def _production_parity_startup() -> None:
    global _corpus_task
    # Pre-deploy tests must never wait for an external Adilet/ZAN refresh. The
    # real Railway runtime has no PYTEST_CURRENT_TEST and therefore starts the
    # same official-source refresh loop as strict_bot.
    if os.getenv("PYTEST_CURRENT_TEST"):
        return
    if _corpus_task is None:
        _corpus_task = start_corpus_refresh_task()


async def _production_parity_shutdown() -> None:
    global _corpus_task
    if _corpus_task is not None:
        _corpus_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _corpus_task
        _corpus_task = None


add_lifespan(app, startup=_production_parity_startup, shutdown=_production_parity_shutdown)


@app.get("/miniapp/parity")
async def parity() -> dict[str, Any]:
    inner = getattr(service, "inner", None)
    stable = getattr(inner, "stable", None)
    return {
        "status": "ok",
        "api_version": "0.8.0",
        "parity_revision": PARITY_REVISION,
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
