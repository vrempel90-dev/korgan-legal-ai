"""Production-safe installer for client-document feedback hardening.

The canonical generator/prepayment installer is never replaced. Client notices
only decorate its authorization function, while legal QA/renderer patches are
idempotent and independent of payment routing.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from korgan import client_document_feedback_hotfix as core
from korgan import client_document_notices as notices

LOGGER = logging.getLogger(__name__)
_INSTALLED = False


def wrap_ensure_prepayment_with_client_notices(
    original: Callable[..., Awaitable[bool]],
) -> Callable[..., Awaitable[bool]]:
    """Add checklist-before-gate and progress-after-authorization semantics."""

    async def ensure_with_notices(message: Any, state: Any, *, kind: str) -> bool:
        try:
            await notices.send_checklist_once(message, state, kind)
        except Exception:
            LOGGER.exception("CLIENT_CHECKLIST_FAILED kind=%s", kind)

        allowed = await original(message, state, kind=kind)
        if not allowed:
            return False

        try:
            await notices.send_progress_once(message, state, kind)
        except Exception:
            LOGGER.exception("GENERATION_PROGRESS_NOTICE_FAILED kind=%s", kind)
        return True

    ensure_with_notices._korgan_progress = True  # type: ignore[attr-defined]
    return ensure_with_notices


def _install_payment_notices() -> None:
    """Decorate only authorization; keep canonical generator assignments intact."""
    from korgan import prepayment_gate

    current = prepayment_gate.ensure_prepayment
    if getattr(current, "_korgan_progress", False):
        return
    prepayment_gate.ensure_prepayment = wrap_ensure_prepayment_with_client_notices(current)


def install_client_document_feedback_safe() -> None:
    """Install CodeRabbit-reviewed QA/UI hooks without payment-routing changes."""
    global _INSTALLED
    if _INSTALLED:
        return
    core.install_research_prompt_patch()
    core.install_quality_patches()
    from korgan import senior_claim_preflight
    setattr(
        senior_claim_preflight.deterministic_claim_preflight,
        "_korgan_claim_consistency_guard",
        True,
    )
    # Официальный заголовок ответа на претензию печатает сам рендерер
    # korgan.pretrial_response: отдельная копия рендерера здесь перекрывала
    # канонический и делала правки канона невидимыми в production.
    _install_payment_notices()
    _INSTALLED = True
    LOGGER.info("Installed KORGAN verified client document feedback hardening")
