from korgan.production_runtime import ProductionOpenAILegalService
from korgan.state_duty_final_hotfix import ProductionOpenAILegalService as FinalLegalService


def test_production_runtime_selects_final_guarded_legal_service() -> None:
    assert ProductionOpenAILegalService is FinalLegalService
