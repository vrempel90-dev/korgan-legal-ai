from __future__ import annotations

from contextvars import ContextVar
from copy import deepcopy
import hashlib
import logging
import time
from typing import Any

from korgan.legal.pipeline import research_from_corpus
from korgan.legal_routing import ClaimProfile, detect_claim_profile
from korgan.legal_types import LegalResearch

LOGGER = logging.getLogger(__name__)

_FAST_RESEARCH_CACHE_TTL_SECONDS = 15 * 60
_FAST_RESEARCH_CACHE_MAX_ENTRIES = 64
_SEARCH_CONTEXT_OVERRIDE: ContextVar[str | None] = ContextVar(
    "korgan_professional_search_context_override",
    default=None,
)


def _research_cache_key(case_context: str, language: str) -> str:
    raw = f"{language}\0{case_context}".encode("utf-8", errors="replace")
    return hashlib.sha256(raw).hexdigest()


def _preferred_search_context(case_context: str) -> str:
    """Use low context for routed/common claims; keep medium for complex profiles."""
    return detect_claim_profile(case_context).search_context_size


def _research_is_sufficient(profile: ClaimProfile, research: LegalResearch) -> bool:
    """A fast pass may replace medium search only when source-bound law is usable."""
    if not research.verified_claims or not research.source_urls:
        return False
    if not profile.required_article_hints:
        return True

    text = "\n".join(str(item) for item in research.verified_claims).lower()
    for article in profile.required_article_hints:
        if article not in text:
            return False
    return True


def _with_search_context(tools: Any, search_context_size: str) -> Any:
    if not isinstance(tools, list):
        return tools
    updated: list[Any] = []
    for item in tools:
        if isinstance(item, dict) and item.get("type") == "web_search":
            copy = dict(item)
            copy["search_context_size"] = search_context_size
            updated.append(copy)
        else:
            updated.append(item)
    return updated


def install_professional_rag_bridge() -> None:
    """Feed local Adilet candidates into source-bound research and reduce latency.

    The local corpus remains a retrieval accelerator, never an authority shortcut.
    For common routed disputes the exact same professional source-bound research
    first verifies the RAG candidates with a low-context web pass.  If that pass
    cannot produce usable official-source law, the current medium-context pass is
    run automatically.  Complex profiles keep medium context from the start.

    Successful exact-case research is cached in memory for 15 minutes so retries
    do not repeat an expensive official web pass.  Weak/unverified research is not
    cached.  No drafting, citation, quality, payment, or document-release rule is
    changed here.
    """
    from korgan import fast_professional_litigation as litigation

    if getattr(litigation, "_korgan_local_rag_bridge_installed", False):
        return

    original_prompt = litigation._professional_research_prompt

    def bridged_prompt(
        case_context: str,
        *,
        max_chars: int,
        checked_on: str,
        **kwargs: Any,
    ) -> str:
        prompt = original_prompt(
            case_context,
            max_chars=max_chars,
            checked_on=checked_on,
            **kwargs,
        )
        try:
            offered = research_from_corpus(case_context, limit=12)
        except Exception:
            LOGGER.exception("Professional RAG candidate lookup failed; keeping web research")
            return prompt
        if offered is None:
            return prompt

        LOGGER.info(
            "PROFESSIONAL_RAG_HINTS candidates=%d sources=%d",
            len(offered.provisions),
            len(offered.source_urls),
        )
        return (
            prompt
            + "\n\nЛОКАЛЬНЫЕ RAG-КАНДИДАТЫ ИЗ КОРПУСА ADILET (НЕ ФАКТЫ ДЕЛА):\n"
            + offered.prompt_block
            + "\n\nПРАВИЛА ДЛЯ ЭТОГО БЛОКА:\n"
            "- используй его только как список кандидатов для проверки;\n"
            "- не считай норму VERIFIED только потому, что она есть в локальном корпусе;\n"
            "- итоговый правовой вывод и точную редакцию всё равно свяжи с реально открытым "
            "официальным источником в текущем source-bound поиске;\n"
            "- если локальный кандидат не подходит фактам или актуальной редакции, отбрось его;\n"
            "- не переносить текст этого служебного блока в фактические обстоятельства иска."
        )

    litigation._professional_research_prompt = bridged_prompt

    original_structured = litigation.FastProfessionalLitigationService._structured_response

    async def context_aware_structured(self: Any, *args: Any, **kwargs: Any) -> Any:
        # The production research method currently asks for medium context.  The
        # per-request ContextVar safely narrows only the first professional legal
        # research call; concurrent Telegram updates cannot leak settings into one
        # another.  Every source-binding rule remains inside the original method.
        if not args and kwargs.get("schema_name") == "korgan_fast_professional_rk_research":
            override = _SEARCH_CONTEXT_OVERRIDE.get()
            if override in {"low", "medium", "high"}:
                kwargs = dict(kwargs)
                kwargs["tools"] = _with_search_context(kwargs.get("tools"), override)
        return await original_structured(self, *args, **kwargs)

    litigation.FastProfessionalLitigationService._structured_response = context_aware_structured  # type: ignore[method-assign]

    original_research = litigation.FastProfessionalLitigationService.research_case

    async def adaptive_research(self: Any, case_context: str, language: str = "ru") -> LegalResearch:
        profile = detect_claim_profile(case_context)
        key = _research_cache_key(case_context, language)
        now = time.monotonic()
        cache: dict[str, tuple[float, LegalResearch]] = getattr(self, "_korgan_fast_research_cache", {})
        if not hasattr(self, "_korgan_fast_research_cache"):
            self._korgan_fast_research_cache = cache

        cached = cache.get(key)
        if cached is not None and now - cached[0] <= _FAST_RESEARCH_CACHE_TTL_SECONDS:
            LOGGER.info("PROFESSIONAL_RAG_RESEARCH cache=HIT profile=%s", profile.code)
            return deepcopy(cached[1])
        if cached is not None:
            cache.pop(key, None)

        first_context = _preferred_search_context(case_context)
        started = time.perf_counter()
        token = _SEARCH_CONTEXT_OVERRIDE.set(first_context)
        try:
            research = await original_research(self, case_context, language=language)
        finally:
            _SEARCH_CONTEXT_OVERRIDE.reset(token)

        fallback = False
        if first_context == "low" and not _research_is_sufficient(profile, research):
            fallback = True
            LOGGER.info(
                "PROFESSIONAL_RAG_RESEARCH fast pass insufficient profile=%s; fallback=medium",
                profile.code,
            )
            token = _SEARCH_CONTEXT_OVERRIDE.set("medium")
            try:
                research = await original_research(self, case_context, language=language)
            finally:
                _SEARCH_CONTEXT_OVERRIDE.reset(token)

        sufficient = _research_is_sufficient(profile, research)
        if sufficient:
            if len(cache) >= _FAST_RESEARCH_CACHE_MAX_ENTRIES:
                oldest = min(cache.items(), key=lambda pair: pair[1][0])[0]
                cache.pop(oldest, None)
            cache[key] = (time.monotonic(), deepcopy(research))

        LOGGER.info(
            "PROFESSIONAL_RAG_RESEARCH profile=%s first_context=%s fallback=%s sufficient=%s seconds=%.2f",
            profile.code,
            first_context,
            fallback,
            sufficient,
            time.perf_counter() - started,
        )
        return research

    litigation.FastProfessionalLitigationService.research_case = adaptive_research  # type: ignore[method-assign]
    litigation._korgan_local_rag_bridge_installed = True
    LOGGER.info("Installed KORGAN professional local-RAG bridge with adaptive latency path")
