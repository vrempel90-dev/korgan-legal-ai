"""Production invariants from the 2026-08-25 live-run review.

This module is deliberately runtime-facing. It does not change model versions,
payment flow, quotas or document taxonomy. It makes every known quality finding
observable, runs the requested verification-first web-context experiment,
canonicalizes repeated research, and stops repair loops that make no progress.

IMPORTANT: install this only after the complete strict runtime stack is loaded.
The package initializer runs too early; strict_bot invokes the installer after
professional consultation + universal Word guards so these wrappers observe the
methods that production really calls.
"""
from __future__ import annotations

import copy
import hashlib
import json
import logging
import re
from collections import OrderedDict
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
_ISSUE_PREFIX_RE = re.compile(
    r"(?i)^(?:T\d+\s*:\s*|FINAL_RELEASE_(?:CITATION|INTEGRITY)\s*:\s*|"
    r"EXEMPLAR_ARCHITECTURE\s*:\s*|SENIOR_PREFLIGHT_SCORE\s*:\s*\d+(?:\.\d+)?/10\s*[—:-]*\s*)"
)


def classify_issue(issue: str) -> BlockerClass:
    """Classify whether the client can actually fix the blocker."""
    text = " ".join(str(issue or "").split()).strip()
    low = text.casefold()
    # KORGAN's own law/citation/paraphrase defects are always INTERNAL even if
    # an old generic message contains words such as "уточните основание".
    if any(re.search(pattern, low, re.I) for pattern in _INTERNAL_PATTERNS):
        return BlockerClass.INTERNAL_QUALITY
    if any(re.search(pattern, low, re.I) for pattern in _USER_DATA_PATTERNS):
        return BlockerClass.NEEDS_USER_DATA
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
    """Exact diagnosis; never reduce Article 469 to 'уточните основание'."""
    user, internal = split_issues(issues)
    lines: list[str] = []
    for item in user[:limit]:
        lines.append(f"• NEEDS_USER_DATA — {item}")
    remaining = max(0, limit - len(lines))
    for item in internal[:remaining]:
        lines.append(f"• INTERNAL_QUALITY — {item}")
    return "\n".join(lines)


def annotate_internal_quality(draft: Any, issues: list[str]) -> None:
    """Mirror each unresolved internal warning into the delivered draft."""
    notes = list(getattr(draft, "verification_notes", []) or [])
    for issue in issues or []:
        marker = internal_marker(issue)
        if marker not in notes:
            notes.append(marker)
    if hasattr(draft, "verification_notes"):
        draft.verification_notes = notes
    try:
        from korgan.legal_types import VerificationStatus
        if hasattr(draft, "status"):
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


def _semantic_issues(raw_issues: list[Any]) -> list[str]:
    normalized: list[str] = []
    for raw in raw_issues or []:
        text = " ".join(str(raw or "").split()).strip()
        if not text:
            continue
        previous = None
        while previous != text:
            previous = text
            text = _ISSUE_PREFIX_RE.sub("", text).strip()
        text = text.rstrip(" .;:").casefold()
        if text and text not in normalized:
            normalized.append(text)
    return sorted(normalized)


def _install_verification_first_research() -> None:
    """Controlled live arm for the user's low-vs-high research hypothesis."""
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
    """Identical input in one worker gets an identical canonical norm set."""
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
        verified, unverified, balanced = research_balance(result)
        if not balanced:
            marker = (
                "INTERNAL_QUALITY: research verification balance failed: "
                f"verified={verified}, unverified={unverified}; требуется дополнительная source-bound проверка"
            )
            if marker not in result.notes:
                result.notes.append(marker)
        cache[key] = copy.deepcopy(result)
        cache.move_to_end(key)
        while len(cache) > _MAX_RESEARCH_CACHE:
            cache.popitem(last=False)
        LOGGER.info(
            "PIPELINE_RESEARCH_BALANCE case=%s verified=%d unverified=%d invariant=%s",
            key[:12], verified, unverified, "PASS" if balanced else "FAIL",
        )
        LOGGER.info("PIPELINE_INVARIANT I9 deterministic_norms=PASS cache=store case=%s", key[:12])
        return result

    deterministic_research._korgan_goal_v2_deterministic = True  # type: ignore[attr-defined]
    cls.research_case = deterministic_research


def _install_research_warning_visibility() -> None:
    """A failed verified>=unverified balance cannot remain log-only for claims."""
    from korgan import fast_professional_litigation as litigation

    cls = litigation.FastProfessionalLitigationService
    current = cls.draft_claim
    if getattr(current, "_korgan_goal_v2_research_visibility", False):
        return

    async def visible_research_warnings(self: Any, case_context: str, research: LegalResearch, language: str = "ru"):
        draft = await current(self, case_context, research, language=language)
        internal = [
            str(note).split(":", 1)[1].strip()
            for note in research.notes or []
            if str(note).startswith("INTERNAL_QUALITY:")
        ]
        if internal:
            annotate_internal_quality(draft, internal)
            LOGGER.warning(
                "PIPELINE_QUALITY_GATE kind=claim issues_after=%d action=DELIVER_WITH_DIAGNOSTIC block_class=INTERNAL_QUALITY source=research_balance",
                len(internal),
            )
        return draft

    visible_research_warnings._korgan_goal_v2_research_visibility = True  # type: ignore[attr-defined]
    cls.draft_claim = visible_research_warnings


def _install_no_progress_repair_guard() -> None:
    """Stop immediately when a repair iteration sees the same blockers again."""
    from korgan import fast_professional_litigation as litigation

    cls = litigation.FastProfessionalLitigationService
    current = cls._quality_repair
    if getattr(current, "_korgan_goal_v2_no_progress", False):
        return
    exact_cache: OrderedDict[str, dict[str, Any]] = OrderedDict()
    last_semantic_by_case: OrderedDict[str, str] = OrderedDict()

    async def no_progress_repair(self: Any, **kwargs: Any) -> dict[str, Any]:
        raw_issues = list(kwargs.get("issues") or [])
        semantic = _semantic_issues(raw_issues)
        case_context = str(kwargs.get("case_context") or "")
        schema_name = str(kwargs.get("schema_name") or "")
        case_key = hashlib.sha256(case_context.encode("utf-8", errors="replace")).hexdigest()
        issue_fp = _json_fingerprint(semantic)
        exact_key = hashlib.sha256((schema_name + "\0" + case_key + "\0" + issue_fp).encode()).hexdigest()

        if exact_key in exact_cache:
            LOGGER.warning(
                "PIPELINE_INVARIANT I7 no_progress_repair=STOP reason=identical_schema_and_blockers schema=%s blockers=%s",
                schema_name,
                semantic[:6],
            )
            return copy.deepcopy(exact_cache[exact_key])

        # The production defect was 8.4 -> 8.4 -> 8.4 with the same blockers
        # through layered schemas. Cross-schema reuse would be unsafe because
        # payload schemas differ, so the second layer simply keeps ITS OWN valid
        # current_payload and does not make another model call.
        if semantic and last_semantic_by_case.get(case_key) == issue_fp:
            current_payload = kwargs.get("current_payload")
            if isinstance(current_payload, dict):
                LOGGER.warning(
                    "PIPELINE_INVARIANT I7 no_progress_repair=STOP reason=unchanged_blockers_cross_layer schema=%s blockers=%s",
                    schema_name,
                    semantic[:6],
                )
                return copy.deepcopy(current_payload)

        result = await current(self, **kwargs)
        exact_cache[exact_key] = copy.deepcopy(result)
        exact_cache.move_to_end(exact_key)
        last_semantic_by_case[case_key] = issue_fp
        last_semantic_by_case.move_to_end(case_key)
        while len(exact_cache) > _MAX_REPAIR_CACHE:
            exact_cache.popitem(last=False)
        while len(last_semantic_by_case) > _MAX_REPAIR_CACHE:
            last_semantic_by_case.popitem(last=False)
        LOGGER.info(
            "PIPELINE_INVARIANT I7 repair_progress_guard=ARMED schema=%s blockers=%s",
            schema_name,
            semantic[:6],
        )
        return result

    no_progress_repair._korgan_goal_v2_no_progress = True  # type: ignore[attr-defined]
    cls._quality_repair = no_progress_repair


def _install_consultation_observability() -> None:
    """Standard I1/I2 log for the already source-bound consultation gate."""
    from korgan.finalized_litigation import FinalizedProductionClaimService
    from korgan.stable_legal_release import StableLegalProductionService

    for target in (StableLegalProductionService, FinalizedProductionClaimService):
        current = target.consult
        if getattr(current, "_korgan_goal_v2_observed", False):
            continue

        async def observed_consult(self: Any, *args: Any, __current=current, **kwargs: Any):
            answer, urls = await __current(self, *args, **kwargs)
            text = str(answer or "")
            visible_issue = any(
                marker in text
                for marker in (
                    "Требует дополнительной проверки",
                    "ТРЕБУЕТ ДОПОЛНИТЕЛЬНОЙ ПРОВЕРКИ",
                    "Қосымша тексер",
                    "[СВЕРИТЬ:",
                )
            )
            LOGGER.info(
                "PIPELINE_QUALITY_GATE kind=consultation issues_after=%d action=%s visible_to_user=%s",
                1 if visible_issue else 0,
                "DELIVER_WITH_DIAGNOSTIC" if visible_issue else "DELIVER",
                visible_issue,
            )
            return answer, urls

        observed_consult._korgan_goal_v2_observed = True  # type: ignore[attr-defined]
        target.consult = observed_consult  # type: ignore[method-assign]


def install_pipeline_invariants_v2() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _install_verification_first_research()
    _install_deterministic_research_cache()
    _install_research_warning_visibility()
    _install_no_progress_repair_guard()
    _install_consultation_observability()
    _INSTALLED = True
    LOGGER.info(
        "Installed PIPELINE GOAL v2 after final runtime stack: blocker classes + visible warnings + high-context research + deterministic norms + no-progress repair stop + consultation observability"
    )
