"""Production-safe activation of KORGAN cost/latency optimizations.

This installer keeps the production model, legal quality thresholds and release
checks unchanged. It enables only deterministic/source-preserving savings plus
one narrowly-scoped repair optimization: an LLM repair is skipped only when
EVERY remaining claim defect requires external user/source data that the model
is not allowed to invent. Substantive legal, monetary, citation and evidence
defects continue through the existing repair path unchanged.
"""

from __future__ import annotations

import copy
import logging
from typing import Any

from korgan import production_cost_speed_optimizer as optimizer
from korgan.legal_types import LegalResearch

LOGGER = logging.getLogger(__name__)
_INSTALLED = False


def _install_safe_futile_repair_skip() -> None:
    """Skip only non-repairable claim AI work without capturing other repair layers.

    The older generic optimizer stores a bound reference to the repair method at
    install time. That is fine in isolation, but the production service has
    several layered document pipelines. Capturing the old method can bypass a
    later contract/response wrapper. This SAFE variant delegates dynamically to
    the next method in the production MRO, so every non-skipped call keeps the
    exact repair implementation that would otherwise have run.
    """
    from korgan import fast_professional_litigation as litigation

    cls = litigation.FastProfessionalLitigationService
    current_direct = cls.__dict__.get("_quality_repair")
    if current_direct is not None and getattr(current_direct, "_korgan_cost_speed_repair_safe", False):
        return

    async def optimized_quality_repair(
        self: Any,
        *,
        schema_name: str,
        schema: dict[str, Any],
        case_context: str,
        research: LegalResearch,
        current_payload: dict[str, Any],
        issues: list[str],
        language: str,
        document_label: str,
        extra_rules: str,
    ) -> dict[str, Any]:
        if (
            schema_name == "korgan_fast_professional_repair"
            and optimizer._all_issues_external_only(issues)
        ):
            LOGGER.info(
                "KORGAN COST_SPEED skipped_nonrepairable_ai_call schema=%s issues=%s",
                schema_name,
                issues[:4],
            )
            return copy.deepcopy(current_payload)

        # Resolve the next repair implementation at call time. This preserves
        # contract/response/test wrappers installed after this optimizer and
        # prevents a claim-only optimization from changing another document path.
        delegate = super(cls, self)._quality_repair
        return await delegate(
            schema_name=schema_name,
            schema=schema,
            case_context=case_context,
            research=research,
            current_payload=current_payload,
            issues=issues,
            language=language,
            document_label=document_label,
            extra_rules=extra_rules,
        )

    optimized_quality_repair._korgan_cost_speed_repair_safe = True  # type: ignore[attr-defined]
    cls._quality_repair = optimized_quality_repair


def install_production_cost_speed_optimizer_safe() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    from korgan.legal import corpus_refresh

    current_refresh = corpus_refresh.refresh_corpus_once
    if not getattr(current_refresh, "_korgan_progressive_bootstrap", False):
        progressive = optimizer._progressive_refresh_factory(
            current_refresh,
            corpus_refresh._load_from_official_sources,
        )
        progressive._korgan_progressive_bootstrap = True  # type: ignore[attr-defined]
        corpus_refresh.refresh_corpus_once = progressive

    # Safe savings only: narrower research scope, low web context when strong
    # local official-law RAG already exists, deterministic verified court
    # registry resolution, and no paid claim-repair call for defects that the
    # model is explicitly forbidden to solve by invention. Mixed/substantive
    # issue sets keep the exact existing repair semantics and quality gates.
    optimizer._install_research_scope_optimizer()
    optimizer._install_rag_search_context_optimizer()
    _install_safe_futile_repair_skip()
    optimizer._install_economic_court_registry()

    _INSTALLED = True
    LOGGER.info(
        "Installed KORGAN production cost/speed optimizer SAFE: progressive verified corpus + RAG-aware web context + claim-only external-data repair skip + economic court registry; models/quality gates unchanged"
    )
