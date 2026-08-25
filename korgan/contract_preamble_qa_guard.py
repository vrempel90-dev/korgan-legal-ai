from __future__ import annotations

import logging
import re
from typing import Any

from korgan.contract_preamble import preamble_defects

LOGGER = logging.getLogger(__name__)

_GENERIC_TEMPLATE_MARKERS = (
    "[организационно-правовая форма",
    "[роль по договору]",
    "[вторая сторона в том же формате]",
)


def _normalize(value: str) -> str:
    return " ".join(str(value or "").split()).strip()


def _is_generic_template_line(value: str) -> bool:
    lowered = value.casefold()
    return any(marker in lowered for marker in _GENERIC_TEMPLATE_MARKERS)


def canonicalize_contract_preamble(draft: Any) -> bool:
    """Collapse model-emitted duplicate preambles to one complete client-specific paragraph.

    Contract QA occasionally receives both a valid party-specific preamble and a
    second universal template copied from the drafting instructions. The latter is
    not a legal defect in the client facts; it is generation scaffolding and must be
    removed deterministically before the expensive validator/repair loop.
    """
    raw_lines = [_normalize(x) for x in (getattr(draft, "preamble", None) or [])]
    lines = [x for x in raw_lines if x]
    if len(lines) < 2:
        return False

    # Prefer a self-contained, non-template preamble. This safely preserves split
    # preambles when no single line independently identifies both parties.
    complete = [
        line for line in lines
        if not _is_generic_template_line(line) and not preamble_defects([line])
    ]
    if not complete:
        # At minimum strip a literal universal template only when another line
        # remains; never delete substantive client text.
        filtered = [line for line in lines if not _is_generic_template_line(line)]
        if filtered and filtered != lines:
            draft.preamble = filtered
            LOGGER.info("CONTRACT_PREAMBLE_QA stripped universal template lines=%d", len(lines) - len(filtered))
            return True
        return False

    chosen = complete[0]
    if lines == [chosen]:
        return False
    draft.preamble = [chosen]
    LOGGER.info("CONTRACT_PREAMBLE_QA canonicalized preamble lines=%d -> 1", len(lines))
    return True


def install_contract_preamble_qa_guard() -> None:
    from korgan import robust_production_legal

    cls = robust_production_legal.ProductionOpenAILegalService
    current = cls.validate_contract
    if getattr(current, "_korgan_preamble_qa_guard", False):
        return

    async def guarded_validate(self: Any, case_context: str, research: Any, draft: Any):
        canonicalize_contract_preamble(draft)
        return await current(self, case_context, research, draft)

    guarded_validate._korgan_preamble_qa_guard = True  # type: ignore[attr-defined]
    cls.validate_contract = guarded_validate  # type: ignore[method-assign]
    LOGGER.info("Installed KORGAN contract preamble QA guard")
