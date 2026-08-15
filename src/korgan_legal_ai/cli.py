from datetime import date
from decimal import Decimal
from uuid import UUID

import typer
from sqlalchemy import create_engine

from korgan_legal_ai.config import Settings
from korgan_legal_ai.corpus.embeddings import OpenAIEmbeddingProvider
from korgan_legal_ai.corpus.repository import LegalNormRepository
from korgan_legal_ai.domain.models import (
    Evidence,
    Fact,
    Financials,
    LegalArea,
    LockedCase,
    Party,
    PartyRole,
    RoutingDecision,
    DocumentType,
)
from korgan_legal_ai.orchestration.factory import build_debt_claim_workflow
from korgan_legal_ai.research.candidates import ResearchCandidateRepository
from korgan_legal_ai.research.review import LawyerReviewService

app = typer.Typer(help="KORGAN Legal AI legal-core CLI")


def _database_engine():
    settings = Settings()
    if not settings.database_url:
        raise typer.BadParameter("DATABASE_URL is required")
    return create_engine(settings.database_url)


def _candidate_repository() -> ResearchCandidateRepository:
    return ResearchCandidateRepository(_database_engine())


@app.command()
def sample() -> None:
    """Run a deterministic debt-claim sample without an API key."""
    debt_fact = Fact(statement="Ответчик не возвратил сумму долга в согласованный срок.")
    case = LockedCase(
        raw_text="Демонстрационный кейс",
        parties=[
            Party(name="ТОО Истец", role=PartyRole.CLAIMANT),
            Party(name="ТОО Ответчик", role=PartyRole.DEFENDANT),
        ],
        facts=[debt_fact],
        evidence=[Evidence(title="Договор", supports_fact_ids=[debt_fact.id])],
        financials=Financials(principal=Decimal("1000000")),
    )
    routing = RoutingDecision(
        document_type=DocumentType.CLAIM,
        legal_area=LegalArea.DEBT_RECOVERY,
        confidence=1.0,
        rationale="Demo",
    )
    result = build_debt_claim_workflow(Settings(openai_api_key=None)).run(case, routing)
    typer.echo(result.document.text)
    typer.echo("\nNEEDS_VERIFICATION: " + ", ".join(result.document.needs_verification))
    typer.echo("STATUS: " + result.document.readiness)


@app.command("review-list")
def review_list(limit: int = typer.Option(100, min=1, max=500)) -> None:
    """List pending official-fallback candidates for a lawyer."""
    candidates = _candidate_repository().list_pending(limit=limit)
    if not candidates:
        typer.echo("No pending_review candidates.")
        return
    for candidate in candidates:
        typer.echo(candidate.model_dump_json(indent=2))


@app.command("review-show")
def review_show(candidate_id: UUID) -> None:
    """Show the exact candidate text/source/date proposal before a decision."""
    candidate = _candidate_repository().get_by_id(candidate_id)
    if candidate is None:
        raise typer.BadParameter("candidate not found")
    typer.echo(candidate.model_dump_json(indent=2))


@app.command("review-approve")
def review_approve(
    candidate_id: UUID,
    reviewed_by: str = typer.Option(..., "--reviewed-by"),
    effective_from: str | None = typer.Option(None, "--effective-from"),
    effective_to: str | None = typer.Option(None, "--effective-to"),
    code_id: str | None = typer.Option(None, "--code-id"),
    law_name: str | None = typer.Option(None, "--law-name"),
    review_note: str | None = typer.Option(None, "--note"),
) -> None:
    """Promote a reviewed pending candidate to canonical and embed it atomically."""
    settings = Settings()
    if not settings.database_url:
        raise typer.BadParameter("DATABASE_URL is required")
    if not settings.openai_api_key:
        raise typer.BadParameter("OPENAI_API_KEY is required to embed an approved canonical norm")
    try:
        parsed_from = date.fromisoformat(effective_from) if effective_from else None
        parsed_to = date.fromisoformat(effective_to) if effective_to else None
    except ValueError as exc:
        raise typer.BadParameter("effective dates must use YYYY-MM-DD") from exc

    engine = create_engine(settings.database_url)
    service = LawyerReviewService(
        ResearchCandidateRepository(engine),
        LegalNormRepository(engine),
        OpenAIEmbeddingProvider(
            api_key=settings.openai_api_key,
            model=settings.korgan_embedding_model,
        ),
    )
    result = service.approve(
        candidate_id,
        reviewed_by=reviewed_by,
        effective_from=parsed_from,
        effective_to=parsed_to,
        code_id=code_id,
        law_name=law_name,
        review_note=review_note,
    )
    typer.echo(result.model_dump_json(indent=2))


@app.command("review-reject")
def review_reject(
    candidate_id: UUID,
    reviewed_by: str = typer.Option(..., "--reviewed-by"),
    reason: str = typer.Option(..., "--reason"),
) -> None:
    """Reject a candidate; it cannot be silently reopened by another fallback search."""
    engine = _database_engine()
    # Rejection never calls OpenAI, so no provider is built here; the repository transition is
    # performed directly.
    repository = ResearchCandidateRepository(engine)
    rejected = repository.mark_rejected(
        candidate_id,
        reviewed_by=reviewed_by,
        reviewed_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        review_note=reason,
    )
    typer.echo(rejected.model_dump_json(indent=2))


if __name__ == "__main__":
    app()
