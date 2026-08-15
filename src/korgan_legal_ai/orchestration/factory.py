from __future__ import annotations

from korgan_legal_ai.blueprints.registry import BLUEPRINTS, CLAIM_DEBT_RECOVERY
from korgan_legal_ai.config import Settings
from korgan_legal_ai.corpus.embeddings import OpenAIEmbeddingProvider
from korgan_legal_ai.corpus.repository import LegalNormRepository
from korgan_legal_ai.corpus.search import HybridSearchService
from korgan_legal_ai.db.engine import build_engine
from korgan_legal_ai.drafting.debt_claim import DebtClaimDrafter
from korgan_legal_ai.drafting.generic import DocumentDrafter
from korgan_legal_ai.fact_lock.service import FactLockService
from korgan_legal_ai.llm.openai_provider import OpenAIProvider
from korgan_legal_ai.orchestration.debt_claim import DebtClaimWorkflow
from korgan_legal_ai.orchestration.document import DocumentWorkflow
from korgan_legal_ai.orchestration.engine import LegalEngine
from korgan_legal_ai.procedural.checker import ProceduralChecker
from korgan_legal_ai.procedural_rules.basis import LegalBasisVerifier
from korgan_legal_ai.procedural_rules.deadlines import DeadlineCalculator
from korgan_legal_ai.procedural_rules.jurisdiction import JurisdictionResolver
from korgan_legal_ai.procedural_rules.repository import ProceduralRuleRepository
from korgan_legal_ai.procedural_rules.state_duty import StateDutyCalculator
from korgan_legal_ai.research.gateway import (
    CanonicalHybridResearchBackend,
    CitationGateway,
)
from korgan_legal_ai.router.service import TaskRouter


def _build_procedural_checker(settings: Settings) -> ProceduralChecker:
    """Build production RAG only when both DB and OpenAI are configured.

    Missing infrastructure never enables a weaker verification path: it returns the
    original fail-closed gateway instead. Misconfigured configured infrastructure is
    allowed to fail loudly rather than silently downgrading legal verification.
    """
    if not settings.database_url or not settings.openai_api_key:
        return ProceduralChecker(CitationGateway())

    engine = build_engine(settings.database_url)
    norm_repository = LegalNormRepository(engine)
    embedding_provider = OpenAIEmbeddingProvider(
        api_key=settings.openai_api_key,
        model=settings.korgan_embedding_model,
    )
    gateway = CitationGateway(
        CanonicalHybridResearchBackend(
            HybridSearchService(norm_repository, embedding_provider)
        )
    )
    rule_repository = ProceduralRuleRepository(engine)
    basis_verifier = LegalBasisVerifier(gateway)
    return ProceduralChecker(
        gateway,
        state_duty_calculator=StateDutyCalculator(rule_repository, basis_verifier),
        jurisdiction_resolver=JurisdictionResolver(rule_repository, basis_verifier),
        deadline_calculator=DeadlineCalculator(rule_repository, basis_verifier),
    )


def build_debt_claim_workflow(settings: Settings) -> DebtClaimWorkflow:
    provider = OpenAIProvider(settings.openai_api_key) if settings.openai_api_key else None
    return DebtClaimWorkflow(
        procedural=_build_procedural_checker(settings),
        drafter=DebtClaimDrafter(
            provider=provider,
            model=settings.korgan_model_draft if provider else None,
        ),
    )


def build_workflows(
    settings: Settings,
    *,
    provider: OpenAIProvider | None = None,
) -> dict[str, DocumentWorkflow]:
    """Build one workflow per registered blueprint.

    Every document type runs the same verified pipeline; only the blueprint differs. A blueprint
    added to the registry therefore becomes available end-to-end without touching this factory.
    """
    checker = _build_procedural_checker(settings)
    model = settings.korgan_model_draft if provider else None
    workflows: dict[str, DocumentWorkflow] = {}
    for blueprint in BLUEPRINTS:
        if blueprint.key == CLAIM_DEBT_RECOVERY.key:
            workflows[blueprint.key] = DebtClaimWorkflow(
                procedural=checker,
                drafter=DebtClaimDrafter(provider=provider, model=model),
            )
            continue
        workflows[blueprint.key] = DocumentWorkflow(
            blueprint=blueprint,
            procedural=checker,
            drafter=DocumentDrafter(blueprint, provider=provider, model=model),
        )
    return workflows


def build_legal_engine(settings: Settings) -> LegalEngine:
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is required to process raw unstructured case text")
    provider = OpenAIProvider(settings.openai_api_key)
    workflows = build_workflows(settings, provider=provider)
    return LegalEngine(
        fact_lock=FactLockService(provider, settings.korgan_model_fact_lock),
        router=TaskRouter(provider, settings.korgan_model_router),
        debt_claim=workflows[CLAIM_DEBT_RECOVERY.key],
        workflows=workflows,
    )
