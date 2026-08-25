"""Production invariants from the 2026-08-25 live-run review.

This module is deliberately runtime-facing.  It does not change the legal model,
payment flow or document taxonomy.  It makes quality findings observable to the
client, forces verification-first research for the experiment requested by the
production review, makes repeated identical research deterministic within a
worker, and suppresses duplicate no-progress repair calls.
"""
from __future__ import annotations

import copy
import hashlib
import json
import logging
import re
from collections import OrderedDict
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from korgan.legal_types import LegalResearch

LOGGER = logging.getLogger(__name__)
_INSTALLED = False
_MAX_RESEARCH_CACHE = 48
_MAX_REPAIR_CACHE = 96


class BlockerClass(StrEnum):
    NEEDS_USER_DATA = "NEEDS_USER_DATA"
    INTERNAL_QUALITY = "INTERNAL_QUALITY"


_USER_DATA_PATTERNS = (
    r"не\s+указан[аоы]?\b",
    r"отсутству(?:ет|ют)\b",
    r"не\s+хватает\s+(?:данных|факт|сведен|документ)",
    r"неизвест(?:ен|на|но|ны)\b",
    r"требует\s+уточнения\s+(?:адрес|бин|иин|реквизит|дата|сумм)",
    r"\b(?:бин|иин|адрес|реквизит)\b.*(?:не\s+указ|отсутств|неизвест)",
    r"(?:документ|квитанц|платежн\w*\s+поручен).*подтвержда",
    r"каких\s+фактов\s+не\s+хватает",
)
_INTERNAL_PATTERNS = (
    r"цитат",
    r"пересказ",
    r"формулиров",
    r"source[- ]bound",
    r"verified",
    r"правов\w*\s+основан",
    r"материальн\w*[- ]прав",
    r"стать[ьяеию]",
    r"\bст\.\s*\d+",
    r"норм[а-я]*\b",
    r"integrity|целостност",
    r"retrieval|research",
    r"обобща\w*\s+узк",
    r"право,?\s+а\s+не\s+обязан",
    r"не\s+подтвержден\w*\s+(?:официальн|source)",
)


def classify_issue(issue: str) -> BlockerClass:
    """Classify whether the client can actually fix the blocker.

    Legal-source/citation/paraphrase defects are always INTERNAL_QUALITY even if
    older text asks the client to "уточнить правовое основание".  A client can
    provide missing facts or documents, but cannot repair KORGAN's own citation.
    """
    text = " ".join(str(issue or "").split()).strip()
    low = text.casefold()
    if any(re.search(pattern, low, re.I) for pattern in _INTERNAL_PATTERNS):
        return BlockerClass.INTERNAL_QUALITY
    if any(re.search(pattern, low, re.I) for pattern in _USER_DATA_PATTERNS):
        return BlockerClass.NEEDS_USER_DATA
    # Unknown quality findings are not pushed onto the client by default.
    return BlockerClass.INTERNAL_QUALITY


def split_issues(issues: list[str]) -> tuple[list[str], list[str]]:
    user: list[str] = []
    internal: list[str] = []
    for raw in issues or []:
        issue = " ".join(str(raw or "").split()).strip()
        if not issue:
            continue
        target = user if classify_issue(issue) is BlockerClass.NEEDS_USER_DATA else internal
        if issue not in target:
            target.append(issue)
    return user, internal


def internal_marker(issue: str) -> str:
    text = " ".join(str(issue or "").split()).strip().rstrip(".")
    return f"[СВЕРИТЬ: {text}]"


def exact_client_diagnostics(kind: str, issues: list[str], *, limit: int = 6) -> str:
    """Return exact, actionable diagnostics instead of a generic quality warning."""
    user, internal = split_issues(issues)
    lines: list[str] = []
    for item in user[:limit]:
        lines.append(f"• NEEDS_USER_DATA — {item}")
    remaining = max(0, limit - len(lines))
    for item in internal[:remaining]:
        lines.append(f"• INTERNAL_QUALITY — {item}")
    if not lines:
        return ""
    return "\n".join(lines)


def annotate_internal_quality(draft: Any, issues: list[str]) -> None:
    """Make every unresolved internal warning visible in the delivered artifact.

    We do not invent a replacement legal proposition.  The exact diagnostic is
    carried as a [СВЕРИТЬ] marker and the draft is therefore preliminary.
    """
    notes = list(getattr(draft, "verification_notes", []) or [])
    for issue in issues or []:
        marker = internal_marker(issue)
        if marker not in notes:
            notes.append(marker)
    if hasattr(draft, "verification_notes"):
        draft.verification_notes = notes
    status = getattr(draft, "status", None)
    try:
        from korgan.legal_types import VerificationStatus
        if status is not None:
            draft.status = VerificationStatus.NEEDS_VERIFICATION
    except Exception:
        pass


def canonicalize_research(research: LegalResearch) -> LegalResearch:
    """Stable ordering/deduplication is mandatory before drafting."""
    research.verified_claims = sorted(dict.fromkeys(str(x).strip() for x in research.verified_claims if str(x).strip()), key=str.casefold)
    research.unverified_claims = sorted(dict.fromkeys(str(x).strip() for x in research.unverified_claims if str(x).strip()), key=str.casefold)
    research.applicable_law = sorted(dict.fromkeys(str(x).strip() for x in research.applicable_law if str(x).strip()), key=str.casefold)
    research.procedural_requirements = sorted(dict.fromkeys(str(x).strip() for x in research.procedural_requirements if str(x).strip()), key=str.casefold)
    research.source_urls = sorted(dict.fromkeys(str(x).strip() for x in research.source_urls if str(x).strip()))
    research.notes = sorted(dict.fromkeys(str(x).strip() for x in research.notes if str(x).strip()), key=str.casefold)
    return research


def research_balance(research: LegalResearch) -> tuple[int, int, bool]:
    verified = len(research.verified_claims or [])
    unverified = len(research.unverified_claims or [])
    return verified, unverified, verified >= unverified


def _json_fingerprint(value: Any) -> str:
    try:
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    except Exception:
        raw = repr(value)
    return hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()


def _install_verification_first_research() -> None:
    """Run the requested low-vs-high experiment with HIGH as the live arm.

    The SAFE cost optimizer may have changed medium -> low for strong local RAG.
    This wrapper is installed afterwards and changes the research web tool to
    high for the source-bound litigation research only.  Logs state the arm so a
    real production run can be compared with the earlier low-context baseline.
    """
    from korgan import fast_professional_litigation as litigation

    cls = litigation.FastProfessionalLitigationService
    current = cls._structured_response
    if getattr(current, "_korgan_goal_v2_high_context", False):
        return

    async def high_context_response(self: Any, **kwargs: Any):
        tools = kwargs.get("tools")
        if kwargs.get("schema_name") == "korgan_fast_professional_rk_research" and tools:
            effective = copy.deepcopy(tools)
            changed = False
            for tool in effective:
                if tool.get("type") == "web_search" and tool.get("search_context_size") != "high":
                    tool["search_context_size"] = "high"
                    changed = True
            kwargs["tools"] = effective
            LOGGER.info(
                "PIPELINE_V2_RESEARCH web_context=high experiment=goal_v2 previous_optimizer_override=%s",
                changed,
            )
        return await current(self, **kwargs)

    high_context_response._korgan_goal_v2_high_context = True  # type: ignore[attr-defined]
    cls._structured_response = high_context_response


def _install_deterministic_research_cache() -> None:
    """Identical input in one worker gets the identical canonical research set."""
    from korgan import fast_professional_litigation as litigation

    cls = litigation.FastProfessionalLitigationService
    current = cls.research_case
    if getattr(current, "_korgan_goal_v2_deterministic", False):
        return
    cache: OrderedDict[str, LegalResearch] = OrderedDict()

    async def deterministic_research(self: Any, case_context: str, language: str = "ru") -> LegalResearch:
        key = hashlib.sha256((language + "\0" + str(case_context or "")).encode("utf-8", errors="replace")).hexdigest()
        cached = cache.get(key)
        if cached is not None:
            cache.move_to_end(key)
            result = copy.deepcopy(cached)
            verified, unverified, balanced = research_balance(result)
            LOGGER.info(
                "PIPELINE_INVARIANT I9 deterministic_norms=PASS cache=hit case=%s verified=%d unverified=%d balanced=%s",
                key[:12], verified, unverified, balanced,
            )
            return result

        result = canonicalize_research(await current(self, case_context, language=language))
        cache[key] = copy.deepcopy(result)
        cache.move_to_end(key)
        while len(cache) > _MAX_RESEARCH_CACHE:
            cache.popitem(last=False)
        verified, unverified, balanced = research_balance(result)
        LOGGER.info(
            "PIPELINE_RESEARCH_BALANCE case=%s verified=%d unverified=%d invariant=%s",
            key[:12], verified, unverified, "PASS" if balanced else "FAIL",
        )
        LOGGER.info("PIPELINE_INVARIANT I9 deterministic_norms=PASS cache=store case=%s", key[:12])
        if not balanced:
            marker = (
                "INTERNAL_QUALITY: research verification balance failed: "
                f"verified={verified}, unverified={unverified}; требуется дополнительная source-bound проверка"
            )
            if marker not in result.notes:
                result.notes.append(marker)
        return result

    deterministic_research._korgan_goal_v2_deterministic = True  # type: ignore[attr-defined]
    cls.research_case = deterministic_research


def _install_no_progress_repair_guard() -> None:
    """Never pay for the same blocker set twice for the same case/schema."""
    from korgan import fast_professional_litigation as litigation

    cls = litigation.FastProfessionalLitigationService
    current = cls._quality_repair
    if getattr(current, "_korgan_goal_v2_no_progress", False):
        return
    cache: OrderedDict[str, dict[str, Any]] = OrderedDict()

    async def no_progress_repair(self: Any, **kwargs: Any) -> dict[str, Any]:
        issues = sorted({" ".join(str(x).split()) for x in (kwargs.get("issues") or []) if str(x).strip()}, key=str.casefold)
        case_context = str(kwargs.get("case_context") or "")
        schema_name = str(kwargs.get("schema_name") or "")
        # Prefixes differ between layered gates; the substantive blocker text is
        # what defines progress.  Keep schema in the key to avoid cross-document
        # schema reuse while still suppressing exact retries inside a gate.
        issue_fp = _json_fingerprint(issues)
        key = hashlib.sha256((schema_name + "\0" + hashlib.sha256(case_context.encode("utf-8", errors="replace")).hexdigest() + "\0" + issue_fp).encode()).hexdigest()
        if key in cache:
            prior = copy.deepcopy(cache[key])
            LOGGER.warning(
                "PIPELINE_INVARIANT I7 no_progress_repair=STOP schema=%s blockers=%s",
                schema_name,
                issues[:6],
            )
            return prior

        result = await current(self, **kwargs)
        cache[key] = copy.deepcopy(result)
        cache.move_to_end(key)
        while len(cache) > _MAX_REPAIR_CACHE:
            cache.popitem(last=False)
        return result

    no_progress_repair._korgan_goal_v2_no_progress = True  # type: ignore[attr-defined]
    cls._quality_repair = no_progress_repair


def install_pipeline_invariants_v2() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    # Must run after production_cost_speed_optimizer_safe so HIGH wins over the
    # earlier low-context optimization for the controlled production comparison.
    _install_verification_first_research()
    _install_deterministic_research_cache()
    _install_no_progress_repair_guard()
    _INSTALLED = True
    LOGGER.info(
        "Installed PIPELINE GOAL v2 primitives: blocker classes + exact diagnostics + high-context research + deterministic research + no-progress repair stop"
    )
