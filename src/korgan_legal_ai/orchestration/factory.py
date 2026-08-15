from __future__ import annotations

from korgan_legal_ai.config import Settings
from korgan_legal_ai.drafting.debt_claim import DebtClaimDrafter
from korgan_legal_ai.fact_lock.service import FactLockService
from korgan_legal_ai.llm.openai_provider import OpenAIProvider
from korgan_legal_ai.orchestration.debt_claim import DebtClaimWorkflow
from korgan_legal_ai.orchestration.engine import LegalEngine
from korgan_legal_ai.procedural.checker import ProceduralChecker
from korgan_legal_ai.research.gateway import CitationGateway
from korgan_legal_ai.router.service import TaskRouter


def build_debt_claim_workflow(settings: Settings) -> DebtClaimWorkflow:
    provider = OpenAIProvider(settings.openai_api_key) if settings.openai_api_key else None
    return DebtClaimWorkflow(
        procedural=ProceduralChecker(CitationGateway()),
        drafter=DebtClaimDrafter(provider=provider, model=settings.korgan_model_draft if provider else None),
    )


def build_legal_engine(settings: Settings) -> LegalEngine:
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is required to process raw unstructured case text")
    provider = OpenAIProvider(settings.openai_api_key)
    return LegalEngine(
        fact_lock=FactLockService(provider, settings.korgan_model_fact_lock),
        router=TaskRouter(provider, settings.korgan_model_router),
        debt_claim=DebtClaimWorkflow(
            procedural=ProceduralChecker(CitationGateway()),
            drafter=DebtClaimDrafter(provider=provider, model=settings.korgan_model_draft),
        ),
    )
