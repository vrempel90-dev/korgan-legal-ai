"""Safe installer for the client-document feedback hardening.

The canonical prepayment installer is intentionally left untouched because it is
a protected production boundary. Only the authorization function is decorated
with a post-authorization progress notice; runtime intake guidance is installed
separately after the canonical prepayment layer.
"""

from __future__ import annotations

import logging
from typing import Any

from korgan import client_document_feedback_hotfix as core

LOGGER = logging.getLogger(__name__)
_INSTALLED = False


def _install_progress_notice() -> None:
    from korgan import prepayment_gate

    current = prepayment_gate.ensure_prepayment
    if getattr(current, "_korgan_progress", False):
        return

    async def ensure_with_progress(message: Any, state: Any, *, kind: str) -> bool:
        allowed = await current(message, state, kind=kind)
        if not allowed:
            return False
        try:
            data = await state.get_data()
            request_id = str(data.get("request_id") or "")
            request_kind = str(data.get("request_kind") or "")
            language = "kk" if str(data.get("language") or "ru") == "kk" else "ru"
            already = (
                str(data.get("generation_progress_request_id") or "") == request_id
                and str(data.get("generation_progress_kind") or "") == kind
            )
            if request_id and request_kind == kind and not already:
                await state.update_data(
                    generation_progress_request_id=request_id,
                    generation_progress_kind=kind,
                )
                await message.answer(core.progress_text(kind, language))
        except Exception:
            LOGGER.exception("GENERATION_PROGRESS_NOTICE_FAILED kind=%s", kind)
        return True

    ensure_with_progress._korgan_progress = True  # type: ignore[attr-defined]
    prepayment_gate.ensure_prepayment = ensure_with_progress


def install_client_document_feedback_safe() -> None:
    """Install feedback fixes without replacing the canonical prepayment installer."""
    global _INSTALLED
    if _INSTALLED:
        return
    core._install_research_prompt_patch()
    core._install_pretrial_quality_patches()
    core._install_claim_consistency_patch()
    core._install_response_title_patch()
    _install_progress_notice()
    _INSTALLED = True
    LOGGER.info("Installed KORGAN verified client document feedback hardening")
