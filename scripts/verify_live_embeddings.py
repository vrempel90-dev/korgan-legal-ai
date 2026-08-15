from __future__ import annotations

import os
from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, text

from korgan_legal_ai.corpus.embeddings import CorpusEmbeddingIndexer, OpenAIEmbeddingProvider
from korgan_legal_ai.corpus.repository import LegalNormRepository
from korgan_legal_ai.corpus.search import HybridSearchService
from korgan_legal_ai.corpus.seed import load_canonical_seed
from korgan_legal_ai.domain.models import VerificationStatus
from korgan_legal_ai.procedural_rules.basis import LegalBasisVerifier
from korgan_legal_ai.procedural_rules.jurisdiction import JurisdictionResolver
from korgan_legal_ai.procedural_rules.repository import ProceduralRuleRepository
from korgan_legal_ai.procedural_rules.seed import load_procedural_rule_seed
from korgan_legal_ai.procedural_rules.state_duty import StateDutyCalculator
from korgan_legal_ai.research.candidates import ResearchCandidateRepository
from korgan_legal_ai.research.fallback import (
    FallbackCitationGateway,
    OfficialFallbackService,
    OpenAIOfficialSearchProvider,
)
from korgan_legal_ai.research.gateway import CanonicalHybridResearchBackend, CitationGateway


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} is required; live acceptance is not allowed to fall back to mocks")
    return value


def main() -> None:
    database_url = require_env("DATABASE_URL")
    openai_api_key = require_env("OPENAI_API_KEY")
    model = os.getenv("KORGAN_EMBEDDING_MODEL", "text-embedding-3-large")
    fallback_model = os.getenv("KORGAN_FALLBACK_MODEL", "gpt-5-mini")

    engine = create_engine(database_url)
    norm_repo = LegalNormRepository(engine)
    candidate_repo = ResearchCandidateRepository(engine)
    rule_repo = ProceduralRuleRepository(engine)
    root = Path(__file__).parents[1]
    reference_seed = load_canonical_seed(root / "data" / "canonical" / "kz_reference_norms.yaml", norm_repo)
    procedural_seed = load_canonical_seed(root / "data" / "canonical" / "kz_procedural_basis_norms.yaml", norm_repo)
    load_procedural_rule_seed(root / "data" / "rules" / "kz_procedural_rules.yaml", rule_repo)
    seeded = reference_seed + procedural_seed

    provider = OpenAIEmbeddingProvider(api_key=openai_api_key, model=model)
    indexer = CorpusEmbeddingIndexer(norm_repo, provider)
    while True:
        result = indexer.index_missing_canonical(batch_size=64)
        if result.indexed == 0:
            break

    with engine.connect() as connection:
        embedded = int(connection.execute(text("""
            SELECT count(*) FROM legal_norms
            WHERE status='canonical' AND embedding IS NOT NULL AND embedding_model=:model
        """), {"model": model}).scalar_one())
    if embedded < len(seeded):
        raise RuntimeError(f"Only {embedded}/{len(seeded)} canonical norms are embedded")

    semantic_query_vector = provider.embed(["неустойка за просрочку оплаты"])[0]
    semantic_matches = norm_repo.semantic_search(
        embedding=semantic_query_vector, event_date=date(2026, 8, 15), limit=3,
    )
    semantic_top = [norm.article_number for norm, _score in semantic_matches]
    if "353" not in semantic_top:
        raise RuntimeError(f"Article 353 was not found in semantic top-3: {semantic_top}")

    hybrid = HybridSearchService(norm_repo, provider)
    exact_hits = hybrid.search("статья 683 ГК РК", event_date=date(2026, 8, 15), limit=3)
    exact_top = [hit.norm.article_number for hit in exact_hits]
    if not exact_top or exact_top[0] != "683":
        raise RuntimeError(f"Exact article 683 was not ranked first by hybrid search: {exact_top}")

    free_hits = hybrid.search(
        "ответственность за неисполнение обязательства", event_date=date(2026, 8, 15), limit=3,
    )
    free_top = [hit.norm.article_number for hit in free_hits]
    if "353" not in free_top or not any(hit.semantic_score > 0 for hit in free_hits):
        raise RuntimeError(f"Hybrid semantic acceptance failed: {free_top}")

    primary = CitationGateway(CanonicalHybridResearchBackend(hybrid))
    basis_verifier = LegalBasisVerifier(primary)
    duty = StateDutyCalculator(rule_repo, basis_verifier).calculate(
        claim_amount_kzt=Decimal("1000000"), claimant_type="legal_entity",
        claim_type="property", event_date=date(2026, 8, 15),
    )
    if duty.status != VerificationStatus.VERIFIED or duty.amount_kzt != Decimal("30000.00"):
        raise RuntimeError(f"Task 9 live state-duty acceptance failed: {duty}")
    jurisdiction = JurisdictionResolver(rule_repo, basis_verifier).resolve(
        plaintiff_type="legal_entity", defendant_type="legal_entity",
        dispute_type="commercial_debt", event_date=date(2026, 8, 15),
    )
    if (
        jurisdiction.status != VerificationStatus.VERIFIED
        or jurisdiction.court_type != "specialized_interdistrict_economic_court"
        or jurisdiction.territorial_rule != "defendant_location"
    ):
        raise RuntimeError(f"Task 9 live jurisdiction acceptance failed: {jurisdiction}")

    official_provider = OpenAIOfficialSearchProvider(api_key=openai_api_key, model=fallback_model)
    fallback_gateway = FallbackCitationGateway(primary, OfficialFallbackService(official_provider, candidate_repo))
    fallback_outcome = fallback_gateway.research(
        "статья 277 ГК РК срок исполнения обязательства", event_date="2026-08-15",
    )
    if fallback_outcome.citations[0].status != VerificationStatus.NEEDS_VERIFICATION:
        raise RuntimeError("Fallback candidate escaped fail-closed user status")
    card = fallback_outcome.review_card
    if card is None or card.article_number != "277" or card.proposed_status != "pending_review":
        raise RuntimeError(f"Official fallback did not stage article 277 correctly: {card}")

    print(
        "LIVE ACCEPTANCE PASSED: "
        f"embedding_model={model}; embedded={embedded}; semantic_top3={semantic_top}; "
        f"exact_683_top3={exact_top}; hybrid_free_top3={free_top}; "
        f"state_duty={duty.amount_kzt}; court_type={jurisdiction.court_type}; "
        f"territorial={jurisdiction.territorial_rule}; fallback_article={card.article_number}; "
        f"fallback_status={card.proposed_status}"
    )


if __name__ == "__main__":
    main()
