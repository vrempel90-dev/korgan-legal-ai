from __future__ import annotations

import logging
import re
from typing import Any, Awaitable, Callable

from korgan import document_quality
from korgan.legal_types import VerificationStatus

LOGGER = logging.getLogger(__name__)
_INSTALLED = False
_ARTICLE_RE = re.compile(r"(?i)(?:стать(?:я|и|е|ю|ёй|ей)|ст\.)\s*\d+(?:-\d+)?")


def _verified(value: Any) -> bool:
    raw = getattr(value, "value", value)
    return str(raw or "").strip().upper() == VerificationStatus.VERIFIED.value.upper()


def _release_issues(context: str, research: Any, draft: Any) -> tuple[Any, list[str]]:
    quality = document_quality.assess_document_quality("claim", context, research, draft)
    issues: list[str] = []

    if not _verified(getattr(research, "status", None)):
        issues.append("правовое исследование не получило статус VERIFIED")
    verified_claims = list(getattr(research, "verified_claims", []) or [])
    if not verified_claims:
        issues.append("нет source-bound подтвержденной материально-правовой основы")

    basis = "\n".join(str(item) for item in list(getattr(draft, "legal_basis", []) or []))
    if not basis.strip():
        issues.append("отсутствует правовое обоснование")
    elif not _ARTICLE_RE.search(basis):
        issues.append("правовое обоснование не содержит конкретных статей законодательства РК")

    if not _verified(getattr(draft, "status", None)):
        issues.append("финальный проект не получил статус VERIFIED")
    if not quality.ready:
        issues.extend(str(item) for item in quality.repair_issues(limit=12))

    notes = [str(item).strip() for item in list(getattr(draft, "verification_notes", []) or []) if str(item).strip()]
    issues.extend(notes[:8])
    return quality, list(dict.fromkeys(item for item in issues if item))


def install_fail_closed_claim_release() -> None:
    """Make Telegram claim delivery a real professional release gate.

    Existing research/drafting/repair logic is unchanged. The only policy change
    is that a claim marked PRELIMINARY/NEEDS_VERIFICATION is never sent as a DOCX.
    This prevents a weak paid draft from being presented as the KORGAN result.
    """
    global _INSTALLED
    if _INSTALLED:
        return

    from korgan import universal_claim_runtime as runtime
    from korgan import bot as base_bot

    original: Callable[..., Awaitable[None]] = runtime._send_claim

    async def guarded_send_claim(
        message: Any,
        state: Any,
        *,
        context: str,
        research: Any,
        draft: Any,
        request_id: str,
    ) -> None:
        quality, issues = _release_issues(context, research, draft)
        if issues:
            LOGGER.error(
                "CLAIM_PROFESSIONAL_RELEASE_BLOCK request_id=%s score=%.1f issues=%s",
                request_id,
                float(getattr(quality, "score", 0.0) or 0.0),
                issues[:8],
            )
            await message.answer(
                "KORGAN не отправил слабый иск: финальная профессиональная проверка не пройдена. "
                "Документ будет выдан только после подтверждённого правового основания, конкретных статей и прохождения QA 10/10.\n\n"
                "Причина: " + "; ".join(issues[:4]),
                reply_markup=base_bot.MENU,
            )
            return

        await original(
            message,
            state,
            context=context,
            research=research,
            draft=draft,
            request_id=request_id,
        )

    runtime._send_claim = guarded_send_claim
    _INSTALLED = True
    LOGGER.info("Installed fail-closed claim release: PRELIMINARY Word delivery disabled")
