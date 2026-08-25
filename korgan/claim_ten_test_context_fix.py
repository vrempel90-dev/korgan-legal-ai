"""Renderer-context bridge for the claim T1-T10 gate.

The DOCX renderer receives only the finalized draft, not the original case text.
Reuse facts/attachments/party blocks as a narrow source context so the final
shape pass does not turn an already documented court cost into a false
"missing payment" marker. No model call or routing change is introduced.
"""
from __future__ import annotations

import logging

from korgan.legal_types import ClaimDraft

LOGGER = logging.getLogger(__name__)
_INSTALLED = False


def install_claim_ten_test_context_fix() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    from korgan import claim_ten_test_gate as gate

    current = gate.ensure_cost_slots
    if getattr(current, "_korgan_render_context", False):
        _INSTALLED = True
        return

    def ensure_with_draft_context(case_context: str, draft: ClaimDraft) -> None:
        context = str(case_context or "").strip()
        if not context:
            context = "\n".join(
                [
                    *[str(item) for item in draft.claimant or []],
                    *[str(item) for item in draft.defendant or []],
                    *[str(item) for item in draft.facts or []],
                    *[str(item) for item in draft.attachments or []],
                    *[str(item) for item in draft.requests or []],
                ]
            )
        current(context, draft)

    ensure_with_draft_context._korgan_render_context = True  # type: ignore[attr-defined]
    gate.ensure_cost_slots = ensure_with_draft_context
    _INSTALLED = True
    LOGGER.info("Installed claim ten-test renderer context bridge")
