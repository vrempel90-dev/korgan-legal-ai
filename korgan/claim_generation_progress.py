"""Request-local progress messages for the live claim research/draft stages."""

from __future__ import annotations

import logging
from contextvars import ContextVar
from typing import Any

LOGGER = logging.getLogger(__name__)
_ACTIVE_CLAIM_MESSAGE: ContextVar[Any | None] = ContextVar("korgan_claim_progress_message", default=None)
_INSTALLED = False


async def _status(text_ru: str, text_kk: str) -> None:
    message = _ACTIVE_CLAIM_MESSAGE.get()
    if message is None:
        return
    try:
        from korgan.language_context import current_language

        await message.bot.send_chat_action(message.chat.id, "typing")
        await message.answer(text_kk if current_language() == "kk" else text_ru)
    except Exception:
        # Progress UI is presentation-only and must never break legal generation.
        LOGGER.exception("KORGAN claim progress status failed; generation continues")


def install_claim_generation_progress() -> None:
    """Show research/draft phase changes without changing any legal method result."""
    global _INSTALLED
    if _INSTALLED:
        return

    from korgan import fast_professional_litigation as litigation
    from korgan import universal_claim_runtime

    current_generate = universal_claim_runtime._generate_now

    async def generate_with_progress(message: Any, state: Any) -> None:
        token = _ACTIVE_CLAIM_MESSAGE.set(message)
        try:
            await current_generate(message, state)
        finally:
            _ACTIVE_CLAIM_MESSAGE.reset(token)

    generate_with_progress._korgan_claim_progress = True  # type: ignore[attr-defined]
    universal_claim_runtime._generate_now = generate_with_progress

    cls = litigation.FastProfessionalLitigationService
    current_research = cls.research_case
    current_draft = cls.draft_claim

    async def research_with_progress(
        self: Any,
        case_context: str,
        language: str = "ru",
    ):
        await _status("🔎 Проверяю применимые нормы…", "🔎 Қолданылатын нормаларды тексеріп жатырмын…")
        return await current_research(self, case_context, language=language)

    async def draft_with_progress(
        self: Any,
        case_context: str,
        research: Any,
        language: str = "ru",
    ):
        await _status("📝 Формирую и проверяю документ…", "📝 Құжатты дайындап, тексеріп жатырмын…")
        return await current_draft(self, case_context, research, language=language)

    research_with_progress._korgan_claim_progress = True  # type: ignore[attr-defined]
    draft_with_progress._korgan_claim_progress = True  # type: ignore[attr-defined]
    cls.research_case = research_with_progress
    cls.draft_claim = draft_with_progress

    _INSTALLED = True
    LOGGER.info("Installed KORGAN claim generation progress: research -> draft")
