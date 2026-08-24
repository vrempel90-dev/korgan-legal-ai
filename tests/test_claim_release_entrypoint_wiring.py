from korgan import claim_release_entrypoint
from korgan.finalized_litigation import FinalizedProductionClaimService


def test_railway_entrypoint_wires_finalized_professional_service(monkeypatch):
    seen: dict[str, object] = {}

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
