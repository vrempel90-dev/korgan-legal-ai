from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from korgan_legal_ai.blueprints.models import STYLE_SUPPORT_ITEM
from korgan_legal_ai.blueprints.registry import CLAIM_DEBT_RECOVERY, blueprint_by_key
from korgan_legal_ai.domain.models import VerificationStatus, WorkflowResult
from korgan_legal_ai.drafting.debt_claim import DebtClaimDrafter
from korgan_legal_ai.drafting.generic import DocumentDrafter
from korgan_legal_ai.evals.cases import EvalCase
from korgan_legal_ai.evals.runner import collect_answers
from korgan_legal_ai.interview import build_locked_case, build_routing
from korgan_legal_ai.orchestration.debt_claim import DebtClaimWorkflow
from korgan_legal_ai.orchestration.document import DocumentWorkflow
from korgan_legal_ai.procedural.checker import ProceduralChecker
from korgan_legal_ai.research.gateway import CitationGateway

# Blockers the corpus of norms can remove. Everything else is about this matter's facts and cannot
# be fixed by adding law, so counting it here would make the corpus look less effective than it is.
LAW_DRIVEN_ITEMS = (
    "jurisdiction",
    "pretrial",
    "limitation",
    "state_duty",
    "authority",
    "attachments",
)
FACT_DRIVEN_ITEMS = (
    "evidence_gaps",
    "claim_total_mismatch",
    "principal_conflicts_with_payments",
    "other_amount_duplicated_debt",
    "penalty_cap_base",
)


@dataclass(frozen=True)
class ItemOutcome:
    case_id: str
    item: str
    status: VerificationStatus
    # True when the item is still unresolved and the norms it needs were not available. False when
    # the norms were verified but a fact is missing — adding law would not move that item.
    blocked_by_missing_norm: bool
    conclusion: str


@dataclass
class NormCoverage:
    """One norm and the case items it moved from unverified to verified."""

    locator: str
    law_name: str
    source_url: str
    unblocked: list[tuple[str, str]] = field(default_factory=list)

    @property
    def unblocked_count(self) -> int:
        return len(self.unblocked)

    @property
    def cases(self) -> tuple[str, ...]:
        return tuple(sorted({case_id for case_id, _ in self.unblocked}))


@dataclass
class CoverageReport:
    as_of: date
    baseline: list[ItemOutcome]
    current: list[ItemOutcome]
    norms: list[NormCoverage]
    corpus_connected: bool

    @property
    def baseline_blockers(self) -> int:
        return sum(
            1 for item in self.baseline if item.status == VerificationStatus.NEEDS_VERIFICATION
        )

    @property
    def remaining_blockers(self) -> int:
        return sum(
            1 for item in self.current if item.status == VerificationStatus.NEEDS_VERIFICATION
        )

    @property
    def remaining_norm_blockers(self) -> int:
        """Still unresolved *and* still waiting on a norm — the part more corpus work can fix."""
        return sum(1 for item in self.current if item.blocked_by_missing_norm)

    @property
    def resolved(self) -> int:
        return self.baseline_blockers - self.remaining_blockers

    @property
    def reduction_percent(self) -> float:
        if not self.baseline_blockers:
            return 0.0
        return round(self.resolved * 100 / self.baseline_blockers, 1)


def _workflow(blueprint, checker: ProceduralChecker, as_of: date) -> DocumentWorkflow:
    if blueprint.key == CLAIM_DEBT_RECOVERY.key:
        return DebtClaimWorkflow(
            procedural=checker, drafter=DebtClaimDrafter(), as_of_date_provider=lambda: as_of
        )
    return DocumentWorkflow(
        blueprint=blueprint,
        procedural=checker,
        drafter=DocumentDrafter(blueprint),
        as_of_date_provider=lambda: as_of,
    )


def _run(case: EvalCase, checker: ProceduralChecker) -> WorkflowResult:
    blueprint = blueprint_by_key(case.blueprint_key)
    state = collect_answers(case)
    locked = build_locked_case(blueprint, state.answers)
    return _workflow(blueprint, checker, case.as_of).run(locked, build_routing(blueprint))


def _outcomes(case: EvalCase, result: WorkflowResult) -> list[ItemOutcome]:
    outcomes: list[ItemOutcome] = []
    for item in result.procedural.items:
        if item.name == STYLE_SUPPORT_ITEM or item.name not in LAW_DRIVEN_ITEMS:
            continue
        unresolved = item.status == VerificationStatus.NEEDS_VERIFICATION
        # If the norms this item rests on came back verified, what is missing is a fact about the
        # matter, not a norm. Adding law would not move it, so it is not counted as corpus work.
        norms_available = bool(item.sources) and all(
            citation.status == VerificationStatus.VERIFIED for citation in item.sources
        )
        outcomes.append(
            ItemOutcome(
                case_id=case.id,
                item=item.name,
                status=item.status,
                blocked_by_missing_norm=unresolved and not norms_available,
                conclusion=item.conclusion,
            )
        )
    return outcomes


def build_coverage_report(
    cases,
    *,
    corpus_checker: ProceduralChecker | None = None,
    as_of: date | None = None,
) -> CoverageReport:
    """Measure how far the corpus has moved the suite off the empty-corpus baseline.

    The baseline is the same suite run against the fail-closed gateway: every legal reference
    unavailable, which is where the corpus starts. Progress is the number of blockers that closed,
    not the number of articles typed in — a norm nobody's case needs moves nothing.
    """
    reference = as_of or date.today()
    baseline_checker = ProceduralChecker(CitationGateway())

    baseline: list[ItemOutcome] = []
    current: list[ItemOutcome] = []
    coverage: dict[tuple[str, str, str], NormCoverage] = {}

    for case in cases:
        baseline_result = _run(case, baseline_checker)
        baseline_outcomes = _outcomes(case, baseline_result)
        baseline.extend(baseline_outcomes)

        if corpus_checker is None:
            current.extend(baseline_outcomes)
            continue

        corpus_result = _run(case, corpus_checker)
        corpus_outcomes = _outcomes(case, corpus_result)
        current.extend(corpus_outcomes)

        was_blocked = {
            outcome.item
            for outcome in baseline_outcomes
            if outcome.status == VerificationStatus.NEEDS_VERIFICATION
        }
        for item in corpus_result.procedural.items:
            if item.name not in was_blocked or item.status != VerificationStatus.VERIFIED:
                continue
            # The citations attached to a now-verified item are exactly the norms that verified it.
            for citation in item.sources:
                if citation.status != VerificationStatus.VERIFIED or not citation.article:
                    continue
                key = (
                    citation.law_name or citation.source_title,
                    citation.article,
                    citation.source_url or "",
                )
                entry = coverage.get(key)
                if entry is None:
                    entry = NormCoverage(
                        locator=f"статья {citation.article}",
                        law_name=citation.law_name or citation.source_title,
                        source_url=citation.source_url or "",
                    )
                    coverage[key] = entry
                entry.unblocked.append((case.id, item.name))

    ranked = sorted(coverage.values(), key=lambda item: (-item.unblocked_count, item.law_name))
    return CoverageReport(
        as_of=reference,
        baseline=baseline,
        current=current,
        norms=ranked,
        corpus_connected=corpus_checker is not None,
    )


def blockers_by_item(outcomes) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for outcome in outcomes:
        if outcome.status == VerificationStatus.NEEDS_VERIFICATION:
            counts[outcome.item] += 1
    return dict(sorted(counts.items(), key=lambda pair: (-pair[1], pair[0])))
