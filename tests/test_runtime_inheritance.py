from korgan.civil_claim_hotfix import ProductionOpenAILegalService as CivilClaimService
from korgan.state_duty_final_hotfix import ProductionOpenAILegalService as FinalService


def test_final_runtime_preserves_civil_claim_hotfix() -> None:
    assert issubclass(FinalService, CivilClaimService)
