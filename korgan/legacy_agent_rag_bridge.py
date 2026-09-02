"""Attach KORGAN's Kazakhstan-only local RAG to the legacy Telegram service.

The live recovery agent still instantiates :class:`OpenAILegalService` directly.
That service already performs source-bound OpenAI web search against official
Kazakhstan domains, so this bridge deliberately does *not* replace that safety
boundary. Local corpus hits are injected only as candidate search hints; every
article/scope/date still has to be confirmed by the existing official-source
web-search pass before it can be treated as verified.
"""

from __future__ import annotations

import logging
from typing import Any

from korgan.legal.pipeline import _ensure_background_bootstrap, research_from_corpus
from korgan.openai_legal import OpenAILegalService

LOGGER = logging.getLogger(__name__)
_INSTALLED_ATTR = "_korgan_kz_local_rag_bridge_installed"
_MAX_HINT_CHARS = 18_000


def _candidate_context(query: str) -> str:
    """Return an explicitly non-authoritative Kazakhstan-law candidate block."""
    try:
        research = research_from_corpus(query, limit=12)
    except Exception:
        LOGGER.exception("LEGACY_AGENT_KZ_RAG candidate retrieval failed safely")
        return ""
    if research is None or not research.prompt_block.strip():
        return ""
    block = research.prompt_block.strip()[:_MAX_HINT_CHARS]
    return (
        "\n\n--- KORGAN LOCAL KZ RAG: ТОЛЬКО ПОИСКОВЫЕ КАНДИДАТЫ ---\n"
        "Следующий блок НЕ является фактом дела и НЕ является VERIFIED-правом. "
        "Он содержит только кандидатов из локального корпуса законодательства Республики Казахстан. "
        "Перед любым точным утверждением о статье, редакции, сроке, сумме, подсудности или применимости "
        "обязательно заново проверь норму текущим source-bound web search по официальному Adilet/ZAN. "
        "Если официальная проверка не подтверждает кандидата — не используй его и пометь вывод NEEDS_VERIFICATION.\n\n"
        f"{block}\n"
        "--- КОНЕЦ ПОИСКОВЫХ КАНДИДАТОВ ---"
    )


def _augment_context(case_context: str, query: str) -> str:
    candidates = _candidate_context(query)
    if not candidates:
        return case_context
    return f"{case_context}{candidates}"


def install_legacy_agent_rag_bridge() -> None:
    """Patch the legacy service once, preserving its official verification pass."""
    if getattr(OpenAILegalService, _INSTALLED_ATTR, False):
        return

    original_init = OpenAILegalService.__init__
    original_research_case = OpenAILegalService.research_case
    original_consult = OpenAILegalService.consult

    def _init(self: OpenAILegalService, *args: Any, **kwargs: Any) -> None:
        original_init(self, *args, **kwargs)
        # OpenAILegalService is constructed inside async bot.main(), so a running
        # event loop is normally present. The helper is intentionally no-op when
        # invoked from a synchronous test/import context.
        _ensure_background_bootstrap()

    async def _research_case(
        self: OpenAILegalService,
        case_context: str,
        language: str = "ru",
    ):
        enriched = _augment_context(case_context, case_context)
        return await original_research_case(self, enriched, language=language)

    async def _consult(
        self: OpenAILegalService,
        question: str,
        case_context: str = "",
        language: str = "ru",
    ):
        query = f"{question}\n{case_context}" if case_context else question
        enriched = _augment_context(case_context, query)
        return await original_consult(
            self,
            question,
            case_context=enriched,
            language=language,
        )

    OpenAILegalService.__init__ = _init  # type: ignore[method-assign]
    OpenAILegalService.research_case = _research_case  # type: ignore[method-assign]
    OpenAILegalService.consult = _consult  # type: ignore[method-assign]
    setattr(OpenAILegalService, _INSTALLED_ATTR, True)
    LOGGER.info("LEGACY_AGENT_KZ_RAG_BRIDGE installed: local candidates + official verification")
