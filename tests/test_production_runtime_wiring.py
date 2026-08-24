from korgan.production_runtime import ProductionOpenAILegalService, bot_module
from korgan.state_duty_final_hotfix import ProductionOpenAILegalService as FinalLegalService


def test_production_runtime_wires_final_guarded_legal_service() -> None:
    assert ProductionOpenAILegalService is FinalLegalService
    assert bot_module.OpenAILegalService is FinalLegalService
