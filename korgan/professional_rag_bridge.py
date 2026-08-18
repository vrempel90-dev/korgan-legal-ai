from __future__ import annotations

from contextvars import ContextVar
from copy import deepcopy
import hashlib
import json
import logging
import re
import time
from typing import Any

from korgan.legal.pipeline import research_from_corpus
from korgan.legal_routing import ClaimProfile, detect_claim_profile
from korgan.legal_types import LegalResearch

LOGGER = logging.getLogger(__name__)

_FAST_RESEARCH_CACHE_TTL_SECONDS = 15 * 60
_FAST_RESEARCH_CACHE_MAX_ENTRIES = 64
_CONSULT_RESEARCH_CACHE_TTL_SECONDS = 5 * 60
_CONSULT_RESEARCH_CACHE_MAX_ENTRIES = 128
_SEARCH_CONTEXT_OVERRIDE: ContextVar[str | None] = ContextVar(
    "korgan_professional_search_context_override",
    default=None,
)
_GK_PROFILES = {"loan_debt", "supply", "services", "work_contract", "lease", "sale", "unjust_enrichment"}


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

    text = "\n".join(str(item) for item in research.verified_claims)
    if profile.code in _GK_PROFILES and not re.search(r"(?i)(?:\bГК\s*РК\b|гражданск\w*\s+кодекс)", text):
        # A contract/debt dispute cannot leave the fast path merely because the
        # search found a procedural provision.  It must carry material GK law.
        return False

    if not profile.required_article_hints:
        return True

    lowered = text.lower()
    return all(
        re.search(rf"(?<!\d){re.escape(article)}(?!\d)", lowered) is not None
        for article in profile.required_article_hints
    )


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


def _consult_query_from_prompt(text: str) -> str:
    match = re.search(r"ВОПРОС:\s*(.*?)\s*КОНТЕКСТ:\s*(.*)$", text, flags=re.IGNORECASE | re.DOTALL)
    if match is None:
        return text[-12000:]
    question = match.group(1).strip()
    context = match.group(2).strip()
    return f"{question}\n{context[:10000]}".strip()


def _compact_consult_research_content(content: Any) -> Any:
    """Guide the existing low-context consultation search without changing authority rules."""
    if not isinstance(content, list) or len(content) != 1 or not isinstance(content[0], dict):
        return content
    role = content[0]
    parts = role.get("content")
    if not isinstance(parts, list) or len(parts) != 1 or not isinstance(parts[0], dict):
        return content
    if parts[0].get("type") != "input_text":
        return content

    text = str(parts[0].get("text", ""))
    if "ЛИМИТ БЫСТРОГО КОНСУЛЬТАЦИОННОГО ПОИСКА" in text:
        return content

    rag_block = ""
    try:
        offered = research_from_corpus(_consult_query_from_prompt(text), limit=6)
    except Exception:
        LOGGER.exception("Consultation RAG candidate lookup failed; keeping web research")
        offered = None
    if offered is not None:
        rag_block = (
            "\n\nКАНДИДАТЫ ИЗ ЛОКАЛЬНОГО КОРПУСА ADILET (ТОЛЬКО ДЛЯ УСКОРЕНИЯ ПРОВЕРКИ):\n"
            + offered.prompt_block
            + "\nСначала проверь наиболее релевантные кандидаты через реально открытый Adilet. "
            "Сам локальный кандидат не является VERIFIED."
        )

    speed_rules = (
        "\n\nЛИМИТ БЫСТРОГО КОНСУЛЬТАЦИОННОГО ПОИСКА:\n"
        "- верни максимум 4 verified_points — только нормы, без которых нельзя ответить на конкретный вопрос;\n"
        "- unresolved_facts: максимум 3; clarifying_questions: максимум 2;\n"
        "- не собирай обзор законодательства и не открывай соседние статьи 'на всякий случай';\n"
        "- начни с наиболее релевантных кандидатов и прекрати поиск, как только правовая основа ответа подтверждена;\n"
        "- если для надёжного вывода компактной проверки недостаточно, честно перенеси пробел в unresolved_facts вместо расширения поиска."
    )

    updated_part = dict(parts[0])
    updated_part["text"] = text + rag_block + speed_rules
    updated_role = dict(role)
    updated_role["content"] = [updated_part]
    return [updated_role]


def _consult_cache_key(instructions: Any, content: Any) -> str:
    raw = json.dumps(
        {"instructions": instructions, "content": content},
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    ).encode("utf-8", errors="replace")
    return hashlib.sha256(raw).hexdigest()


def install_professional_rag_bridge() -> None:
    """Use local Adilet candidates to reduce latency without weakening verification.

    Documents: common routed disputes first verify RAG candidates with low-context
    source-bound web search and automatically fall back to the old medium pass if
    the material-law backbone is insufficient.  Successful exact-case research is
    cached for 15 minutes.

    Consultations: the existing low-context Adilet search is kept, but receives up
    to six local candidates and a strict relevance budget (max four verified legal
    points).  Exact repeated research is cached for five minutes.  Local corpus
    content never becomes VERIFIED by itself.

    Drafting, citations, deterministic QA, payments, quota, and document release
    are untouched.
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
        if args:
            return await original_structured(self, *args, **kwargs)

        schema_name = kwargs.get("schema_name")
        if schema_name == "korgan_fast_professional_rk_research":
            override = _SEARCH_CONTEXT_OVERRIDE.get()
            if override in {"low", "medium", "high"}:
                kwargs = dict(kwargs)
                kwargs["tools"] = _with_search_context(kwargs.get("tools"), override)
            return await original_structured(self, **kwargs)

        if schema_name == "korgan_consult_research":
            original_content = kwargs.get("content")
            cache_key = _consult_cache_key(kwargs.get("instructions"), original_content)
            now = time.monotonic()
            cache: dict[str, tuple[float, Any, Any]] = getattr(self, "_korgan_consult_research_cache", {})
            if not hasattr(self, "_korgan_consult_research_cache"):
                self._korgan_consult_research_cache = cache

            cached = cache.get(cache_key)
            if cached is not None and now - cached[0] <= _CONSULT_RESEARCH_CACHE_TTL_SECONDS:
                LOGGER.info("CONSULT_RAG_RESEARCH cache=HIT")
                return deepcopy(cached[1]), cached[2]
            if cached is not None:
                cache.pop(cache_key, None)

            kwargs = dict(kwargs)
            kwargs["content"] = _compact_consult_research_content(original_content)
            result = await original_structured(self, **kwargs)

            if len(cache) >= _CONSULT_RESEARCH_CACHE_MAX_ENTRIES:
                oldest = min(cache.items(), key=lambda pair: pair[1][0])[0]
                cache.pop(oldest, None)
            cache[cache_key] = (time.monotonic(), deepcopy(result[0]), result[1])
            return result

        return await original_structured(self, **kwargs)

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
    LOGGER.info("Installed KORGAN professional/consultation RAG latency bridge")
