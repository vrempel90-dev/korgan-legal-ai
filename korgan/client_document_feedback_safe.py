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
from korgan import client_feedback_20260825 as client_feedback
from korgan.claim_exemplar_architecture import install_claim_exemplar_architecture
from korgan.claim_exemplar_style import install_claim_exemplar_style
from korgan.claim_money_authority import install_claim_money_authority
from korgan.claim_ten_test_context_fix import install_claim_ten_test_context_fix
from korgan.claim_ten_test_gate import install_claim_ten_test_gate
from korgan.contract_preamble_qa_guard import install_contract_preamble_qa_guard
from korgan.production_cost_speed_optimizer_safe import install_production_cost_speed_optimizer_safe

LOGGER = logging.getLogger(__name__)
_INSTALLED = False


def wrap_ensure_prepayment_with_client_notices(
    original: Callable[..., Awaitable[bool]],
) -> Callable[..., Awaitable[bool]]:
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
    from korgan import prepayment_gate

    current = prepayment_gate.ensure_prepayment
    if getattr(current, "_korgan_progress", False):
        return
    prepayment_gate.ensure_prepayment = wrap_ensure_prepayment_with_client_notices(current)


def install_client_document_feedback_safe() -> None:
    """Install verified QA/UI hooks without payment-routing changes."""
    global _INSTALLED
    if _INSTALLED:
        return
    core.install_research_prompt_patch()
    core.install_quality_patches()
    client_feedback.install_client_feedback_20260825()
    install_contract_preamble_qa_guard()
    install_claim_exemplar_style()
    install_claim_exemplar_architecture()
    install_claim_ten_test_gate()
    install_claim_ten_test_context_fix()
    install_claim_money_authority()

    # The safe optimizer is package-initialization compatible. Goal-v2 itself is
    # deliberately NOT installed here: korgan.__init__ runs before strict_bot has
    # layered the professional consultation and universal Word guards. strict_bot
    # installs Goal-v2 after those layers so its HIGH-research/no-progress wrappers
    # observe the actual production methods instead of stale pre-wrapper methods.
    install_production_cost_speed_optimizer_safe()

    from korgan import senior_claim_preflight
    setattr(
        senior_claim_preflight.deterministic_claim_preflight,
        "_korgan_claim_consistency_guard",
        True,
    )
    core.install_response_title_patch()
    _install_payment_notices()
    _INSTALLED = True
    LOGGER.info("Installed KORGAN verified client document feedback hardening; Goal-v2 deferred to strict runtime")
