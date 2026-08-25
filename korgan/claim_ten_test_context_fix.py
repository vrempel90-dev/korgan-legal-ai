"""Renderer bridge for the claim T1-T10 gate.

The architecture gate owns substantive repairs and cost-slot completion while it
still has the original case context.  The DOCX boundary must never add new
petition items because doing so would change numbering after arithmetic/QA.
This bridge unwraps that broad renderer wrapper and replaces it with a copy-only
marker/transition normalization pass.
"""
from __future__ import annotations

import copy
import logging
from collections.abc import Callable

from korgan.legal_types import ClaimDraft

LOGGER = logging.getLogger(__name__)
_INSTALLED = False


def _unwrap_claim_builder(builder: Callable[[ClaimDraft], bytes]) -> Callable[[ClaimDraft], bytes]:
    if not getattr(builder, "_korgan_ten_test", False):
        return builder
    for cell in builder.__closure__ or ():
        candidate = cell.cell_contents
        if callable(candidate) and getattr(candidate, "__name__", "") == "build_claim_docx":
            return candidate
    return builder


def install_claim_ten_test_context_fix() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    from korgan import claim_docx
    from korgan import claim_ten_test_gate as gate

    current_cost = gate.ensure_cost_slots
    if not getattr(current_cost, "_korgan_render_context", False):
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
            current_cost(context, draft)

        ensure_with_draft_context._korgan_render_context = True  # type: ignore[attr-defined]
        gate.ensure_cost_slots = ensure_with_draft_context

    current_builder = claim_docx.build_claim_docx
    if not getattr(current_builder, "_korgan_ten_test_safe_renderer", False):
        original_builder = _unwrap_claim_builder(current_builder)

        def build_with_safe_markers(draft: ClaimDraft) -> bytes:
            visible = copy.deepcopy(draft)
            gate.ensure_gap_markers("", visible)
            gate.rewrite_duplicate_transitions(visible)
            return original_builder(visible)

        build_with_safe_markers._korgan_ten_test_safe_renderer = True  # type: ignore[attr-defined]
        claim_docx.build_claim_docx = build_with_safe_markers

    _INSTALLED = True
    LOGGER.info("Installed claim ten-test renderer bridge: copy-only markers, stable prayer numbering")
