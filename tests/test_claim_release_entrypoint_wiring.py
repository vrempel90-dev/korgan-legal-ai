from korgan import claim_release_entrypoint
from korgan.finalized_litigation import FinalizedProductionClaimService
from korgan.openai_legal import OpenAILegalService


def test_finalized_service_preserves_openai_service_interface():
    assert issubclass(FinalizedProductionClaimService, OpenAILegalService)
    for method in ("extract_document", "consult", "research_case", "draft_claim"):
        assert callable(getattr(FinalizedProductionClaimService, method, None))


def test_railway_entrypoint_wires_finalized_professional_service(monkeypatch):
    seen: dict[str, object] = {}

    # Register the original factory with monkeypatch so teardown restores it
    # even though entrypoint.main() assigns the production class directly.
    original_factory = claim_release_entrypoint.bot.OpenAILegalService
    monkeypatch.setattr(claim_release_entrypoint.bot, "OpenAILegalService", original_factory)
    monkeypatch.setattr(
        claim_release_entrypoint.claim_quality_hotfix,
        "install_runtime_hotfix",
        lambda: seen.setdefault("hotfix", True),
    )

    async def fake_main():
        seen["service_factory"] = claim_release_entrypoint.bot.OpenAILegalService

    monkeypatch.setattr(claim_release_entrypoint.bot, "main", fake_main)
    claim_release_entrypoint.main()

    assert seen["hotfix"] is True
    assert seen["service_factory"] is FinalizedProductionClaimService
