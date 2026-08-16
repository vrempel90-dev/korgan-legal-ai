from datetime import date
from pathlib import Path
from decimal import Decimal
from uuid import UUID

import typer
from sqlalchemy import create_engine

from korgan_legal_ai.config import Settings
from korgan_legal_ai.corpus.curation import (
    CorpusCurator,
    CurationError,
    NormSubmission,
    check_source,
)
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
from korgan_legal_ai.procedural.checker import ProceduralChecker
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


def _norm_repository() -> LegalNormRepository:
    return LegalNormRepository(_database_engine())


def _parse_date(value: str | None, label: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise typer.BadParameter(f"{label} должна быть в формате ГГГГ-ММ-ДД") from exc


def _submission(
    *,
    code_id: str,
    article: str,
    text_value: str,
    text_file: str | None,
    effective_from: str,
    source_url: str,
    reviewed_by: str,
    law_name: str | None,
    title: str | None,
    part: str,
    point: str,
    effective_to: str | None,
    document_types: str | None,
    next_review: str | None,
    review_months: int,
) -> NormSubmission:
    body = text_value
    if text_file:
        # Article wordings are long and contain quotes and line breaks; a file avoids the shell
        # mangling a text that has to be reproduced verbatim in a citation.
        try:
            body = Path(text_file).read_text(encoding="utf-8")
        except OSError as exc:
            raise typer.BadParameter(f"не удалось прочитать файл с текстом: {exc}") from exc
    if not body:
        raise typer.BadParameter("укажите текст нормы через --text или --text-file")

    parsed_from = _parse_date(effective_from, "--effective-from")
    if parsed_from is None:
        raise typer.BadParameter("--effective-from обязателен")

    types = tuple(
        item.strip() for item in (document_types or "").split(",") if item.strip()
    )
    return NormSubmission(
        code_id=code_id,
        article_number=article,
        text=body,
        effective_from=parsed_from,
        source_url=source_url,
        reviewed_by=reviewed_by,
        law_name=law_name,
        title=title,
        part=part,
        point=point,
        effective_to=_parse_date(effective_to, "--effective-to"),
        applicable_document_types=types,
        next_review_date=_parse_date(next_review, "--next-review"),
        review_months=review_months,
    )


def _echo_result(result, *, action: str) -> None:
    norm = result.norm
    locator = norm.article_number
    if norm.part:
        locator += f", часть {norm.part}"
    if norm.point:
        locator += f", пункт {norm.point}"
    typer.echo(f"{action}: {norm.code_id} статья {locator}")
    typer.echo(f"  редакция с: {norm.effective_from}")
    typer.echo(f"  подтвердил: {norm.reviewed_by}")
    typer.echo(f"  переверификация до: {norm.next_review_date}")
    typer.echo(f"  типы дел: {', '.join(norm.applicable_document_types) or 'не указаны'}")
    typer.echo(f"  источник: {result.source.message}")
    if result.superseded is not None:
        typer.echo(
            f"  предыдущая редакция закрыта: {result.superseded.effective_from} — "
            f"{result.superseded.effective_to} (сохранена в корпусе)"
        )
    for warning in result.warnings:
        typer.echo(f"  ⚠ {warning}")


@app.command("add-norm")
def add_norm(
    code_id: str = typer.Option(..., "--code-id", help="ГК_РК / GPK_RK / TAX_RK_2025 и т.п."),
    article: str = typer.Option(..., "--article", help="Номер статьи"),
    effective_from: str = typer.Option(..., "--effective-from", help="Дата вступления редакции в силу, ГГГГ-ММ-ДД"),
    source_url: str = typer.Option(..., "--source-url", help="Ссылка на официальный источник"),
    reviewed_by: str = typer.Option(..., "--reviewed-by", help="Кто подтвердил норму"),
    text_value: str = typer.Option("", "--text", help="Дословный текст нормы"),
    text_file: str | None = typer.Option(None, "--text-file", help="Файл с дословным текстом нормы"),
    law_name: str | None = typer.Option(None, "--law-name", help="Полное название кодекса/закона"),
    title: str | None = typer.Option(None, "--title", help="Заголовок статьи"),
    part: str = typer.Option("", "--part", help="Часть"),
    point: str = typer.Option("", "--point", help="Пункт"),
    effective_to: str | None = typer.Option(None, "--effective-to"),
    document_types: str | None = typer.Option(
        None, "--document-types", help="Типы дел через запятую: claim,pretrial_demand,appeal"
    ),
    next_review: str | None = typer.Option(None, "--next-review", help="Дата плановой переверификации"),
    review_months: int = typer.Option(6, "--review-months", min=1, max=60),
    allow_unofficial_source: bool = typer.Option(False, "--allow-unofficial-source"),
) -> None:
    """Добавить норму в корпус. Неполные данные отклоняются."""
    curator = CorpusCurator(_norm_repository())
    submission = _submission(
        code_id=code_id, article=article, text_value=text_value, text_file=text_file,
        effective_from=effective_from, source_url=source_url, reviewed_by=reviewed_by,
        law_name=law_name, title=title, part=part, point=point, effective_to=effective_to,
        document_types=document_types, next_review=next_review, review_months=review_months,
    )
    try:
        result = curator.add(submission, allow_unofficial_source=allow_unofficial_source)
    except CurationError as exc:
        typer.echo(f"Норма не сохранена: {exc}")
        raise typer.Exit(code=1) from exc
    _echo_result(result, action="Добавлена норма")


@app.command("update-norm")
def update_norm(
    code_id: str = typer.Option(..., "--code-id"),
    article: str = typer.Option(..., "--article"),
    effective_from: str = typer.Option(..., "--effective-from", help="Дата новой редакции"),
    source_url: str = typer.Option(..., "--source-url"),
    reviewed_by: str = typer.Option(..., "--reviewed-by"),
    text_value: str = typer.Option("", "--text"),
    text_file: str | None = typer.Option(None, "--text-file"),
    law_name: str | None = typer.Option(None, "--law-name"),
    title: str | None = typer.Option(None, "--title"),
    part: str = typer.Option("", "--part"),
    point: str = typer.Option("", "--point"),
    effective_to: str | None = typer.Option(None, "--effective-to"),
    document_types: str | None = typer.Option(None, "--document-types"),
    next_review: str | None = typer.Option(None, "--next-review"),
    review_months: int = typer.Option(6, "--review-months", min=1, max=60),
    allow_unofficial_source: bool = typer.Option(False, "--allow-unofficial-source"),
    correct_in_place: bool = typer.Option(
        False, "--correct-in-place", help="Исправить опечатку в той же редакции, не создавая новую"
    ),
) -> None:
    """Записать новую редакцию нормы. Предыдущая закрывается, но остаётся в корпусе."""
    curator = CorpusCurator(_norm_repository())
    submission = _submission(
        code_id=code_id, article=article, text_value=text_value, text_file=text_file,
        effective_from=effective_from, source_url=source_url, reviewed_by=reviewed_by,
        law_name=law_name, title=title, part=part, point=point, effective_to=effective_to,
        document_types=document_types, next_review=next_review, review_months=review_months,
    )
    try:
        result = curator.update(
            submission,
            allow_unofficial_source=allow_unofficial_source,
            correct_in_place=correct_in_place,
        )
    except CurationError as exc:
        typer.echo(f"Норма не обновлена: {exc}")
        raise typer.Exit(code=1) from exc
    _echo_result(result, action="Обновлена норма")


@app.command("list-pending")
def list_pending(
    as_of: str | None = typer.Option(None, "--as-of", help="Дата проверки, по умолчанию сегодня"),
    limit: int = typer.Option(200, "--limit", min=1, max=1000),
) -> None:
    """Показать нормы, у которых прошёл срок плановой переверификации."""
    reference = _parse_date(as_of, "--as-of") or date.today()
    overdue = CorpusCurator(_norm_repository()).due_for_review(as_of=reference, limit=limit)
    if not overdue:
        typer.echo(f"На {reference} просроченных норм нет.")
        return
    typer.echo(f"Просрочена переверификация ({len(overdue)}) на {reference}:")
    for norm in overdue:
        locator = norm.article_number
        if norm.part:
            locator += f", часть {norm.part}"
        if norm.point:
            locator += f", пункт {norm.point}"
        days = (reference - norm.next_review_date).days
        typer.echo(
            f"  {norm.code_id} статья {locator} — срок истёк {norm.next_review_date} "
            f"({days} дн. назад), подтверждал: {norm.reviewed_by or 'не указан'}"
        )
        typer.echo(f"    источник: {norm.source_url}")


@app.command("verify-source")
def verify_source(url: str = typer.Argument(..., help="Ссылка на источник нормы")) -> None:
    """Проверить, что ссылка ведёт на официальный источник."""
    result = check_source(url)
    typer.echo(("OK: " if result.official else "ВНИМАНИЕ: ") + result.message)
    if not result.official:
        raise typer.Exit(code=1)


class _OfflineEmbeddings:
    """Zero vectors for the coverage report.

    Exact article locators are resolved straight from the corpus and need no embeddings, so the
    report runs without an API key. Free-text semantic search simply finds nothing rather than
    failing, which understates coverage instead of inventing it.
    """

    @property
    def model(self) -> str:
        return "coverage-report-offline"

    def embed(self, texts: list[str]) -> list[list[float]]:
        from korgan_legal_ai.corpus.embeddings import EMBEDDING_DIMENSIONS

        return [[0.0] * EMBEDDING_DIMENSIONS for _ in texts]


def _corpus_checker() -> ProceduralChecker | None:
    """Procedural checker backed by the real corpus, or None when it is not configured."""
    from korgan_legal_ai.corpus.search import HybridSearchService
    from korgan_legal_ai.procedural_rules.basis import LegalBasisVerifier
    from korgan_legal_ai.procedural_rules.deadlines import DeadlineCalculator
    from korgan_legal_ai.procedural_rules.jurisdiction import JurisdictionResolver
    from korgan_legal_ai.procedural_rules.repository import ProceduralRuleRepository
    from korgan_legal_ai.procedural_rules.state_duty import StateDutyCalculator
    from korgan_legal_ai.research.gateway import CanonicalHybridResearchBackend, CitationGateway

    settings = Settings()
    if not settings.database_url:
        return None
    engine = create_engine(settings.database_url)
    norms = LegalNormRepository(engine)
    if norms.count() == 0:
        return None

    gateway = CitationGateway(
        CanonicalHybridResearchBackend(HybridSearchService(norms, _OfflineEmbeddings()))
    )
    rules = ProceduralRuleRepository(engine)
    verifier = LegalBasisVerifier(gateway)
    return ProceduralChecker(
        gateway,
        state_duty_calculator=StateDutyCalculator(rules, verifier),
        jurisdiction_resolver=JurisdictionResolver(rules, verifier),
        deadline_calculator=DeadlineCalculator(rules, verifier),
    )


@app.command("coverage-report")
def coverage_report(
    as_of: str | None = typer.Option(None, "--as-of", help="Дата расчёта, по умолчанию сегодня"),
    include_acceptance: bool = typer.Option(
        False, "--include-acceptance", help="Добавить приёмочные кейсы к прогону"
    ),
) -> None:
    """Показать, насколько корпус норм снизил число блокеров NEEDS_VERIFICATION."""
    from korgan_legal_ai.evals.cases import ACCEPTANCE_CASES, EVAL_CASES
    from korgan_legal_ai.evals.coverage import (
        FACT_DRIVEN_ITEMS,
        blockers_by_item,
        build_coverage_report,
    )

    cases = list(EVAL_CASES) + (list(ACCEPTANCE_CASES) if include_acceptance else [])
    reference = _parse_date(as_of, "--as-of") or date.today()
    checker = _corpus_checker()
    report = build_coverage_report(cases, corpus_checker=checker, as_of=reference)

    typer.echo(f"Кейсов в прогоне: {len(cases)}; дата: {reference}")
    if not report.corpus_connected:
        typer.echo(
            "Корпус не подключён (нет DATABASE_URL или корпус пуст) — показана только базовая линия."
        )
    typer.echo("")
    typer.echo(f"Базовая линия (пустой корпус): {report.baseline_blockers} блокеров по нормам")
    typer.echo(f"Сейчас:                        {report.remaining_blockers} блокеров")
    typer.echo(f"Снято:                         {report.resolved} ({report.reduction_percent}%)")
    typer.echo(
        f"Из оставшихся ждут нормы:      {report.remaining_norm_blockers} "
        "(остальные ждут фактов по делу, наполнение корпуса их не закроет)"
    )
    typer.echo("")
    typer.echo("Оставшиеся блокеры по видам:")
    remaining = blockers_by_item(report.current)
    if not remaining:
        typer.echo("  нет")
    for name, count in remaining.items():
        typer.echo(f"  {name}: {count}")

    typer.echo("")
    typer.echo("Вклад норм (сколько пунктов дела каждая норма перевела в подтверждённые):")
    if not report.norms:
        typer.echo("  ни одна норма пока не сняла ни одного блокера")
    for norm in report.norms:
        typer.echo(f"  {norm.law_name}, {norm.locator} — {norm.unblocked_count} пункт(ов)")
        typer.echo(f"    кейсы: {', '.join(norm.cases)}")
    typer.echo("")
    typer.echo(
        "Категории вне корпуса норм (не учитываются в метрике): " + ", ".join(FACT_DRIVEN_ITEMS)
    )


@app.command("position-list")
def position_list() -> None:
    """Показать зафиксированные позиции по спорным юридическим вопросам."""
    from korgan_legal_ai.positions import KNOWN_QUESTIONS, load_positions

    registry = load_positions()
    for position in registry.all():
        typer.echo(f"{position.key}: {position.decision}")
        typer.echo(f"  вопрос: {position.question}")
        typer.echo(f"  обоснование: {position.rationale}")
        typer.echo(f"  источник: {position.source_label}")
        typer.echo(f"  решил: {position.decided_by} ({position.decided_at})")
        typer.echo(f"  подтверждено юротделом: {'да' if position.confirmed else 'нет'}")
    for key in registry.unanswered():
        question, options, fallback = KNOWN_QUESTIONS[key]
        typer.echo(f"{key}: РЕШЕНИЕ НЕ ЗАФИКСИРОВАНО")
        typer.echo(f"  вопрос: {question}")
        typer.echo(f"  сейчас применяется значение по умолчанию: {fallback}")
        typer.echo(f"  допустимые варианты: {', '.join(options)}")


@app.command("position-set")
def position_set(
    key: str = typer.Option(..., "--key", help="Идентификатор вопроса, см. position-list"),
    decision: str = typer.Option(..., "--decision", help="Выбранный вариант"),
    rationale: str = typer.Option(..., "--rationale", help="Обоснование решения"),
    decided_by: str = typer.Option(..., "--decided-by", help="Кто принял решение"),
    practice_reference: str = typer.Option(
        "", "--practice", help="Ссылка на судебную практику, если решение на неё опирается"
    ),
    decided_at: str | None = typer.Option(None, "--decided-at"),
    confirmed: bool = typer.Option(False, "--confirmed", help="Решение утверждено юротделом"),
) -> None:
    """Зафиксировать позицию фирмы по спорному вопросу. Код при этом не меняется."""
    from korgan_legal_ai.positions import KNOWN_QUESTIONS, LegalPosition, save_position

    known = KNOWN_QUESTIONS.get(key)
    if known is None:
        typer.echo(f"Неизвестный вопрос: {key}. Доступны: {', '.join(KNOWN_QUESTIONS)}")
        raise typer.Exit(code=1)

    question, options, _ = known
    position = LegalPosition(
        key=key,
        question=question,
        decision=decision,
        options=options,
        rationale=rationale,
        decided_by=decided_by,
        decided_at=_parse_date(decided_at, "--decided-at") or date.today(),
        practice_reference=practice_reference,
        confirmed=confirmed,
    )
    try:
        path = save_position(position)
    except ValueError as exc:
        typer.echo(f"Решение не сохранено: {exc}")
        raise typer.Exit(code=1) from exc
    typer.echo(f"Позиция сохранена: {key} = {decision}")
    typer.echo(f"  файл: {path}")
    typer.echo(f"  источник: {position.source_label}")


if __name__ == "__main__":
    app()
