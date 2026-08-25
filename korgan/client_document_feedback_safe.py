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
from korgan.claim_ten_test_gate import install_claim_ten_test_gate
from korgan.contract_preamble_qa_guard import install_contract_preamble_qa_guard
from korgan.production_cost_speed_optimizer_safe import install_production_cost_speed_optimizer_safe

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
    """Install verified QA/UI hooks without payment-routing changes."""
    global _INSTALLED
    if _INSTALLED:
        return
    core.install_research_prompt_patch()
    core.install_quality_patches()
    client_feedback.install_client_feedback_20260825()
    install_contract_preamble_qa_guard()
    # Style makes the Word output look like the exemplars; architecture makes
    # the reasoning/petitum follow their professional pleading structure.
    install_claim_exemplar_style()
    install_claim_exemplar_architecture()
    # The T1-T10 objective decorates the existing architecture repair rather
    # than adding another model round. Final DOCX normalization only inserts
    # honest [ДАННЫЕ]/[СВЕРИТЬ] gaps and judicial-cost slots for debt claims.
    install_claim_ten_test_gate()
    # One deterministic monetary ledger owns claim price. State-duty routing
    # consumes that ledger and may only restore a dropped amount when the exact
    # price is independently present in the user's materials.
    install_claim_money_authority()
    # Cost/speed optimization is deliberately installed after all claim quality
    # layers. The SAFE installer trims only deterministic/research overhead and
    # leaves every existing model repair and release gate untouched.
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
    LOGGER.info("Installed KORGAN verified client document feedback hardening")
