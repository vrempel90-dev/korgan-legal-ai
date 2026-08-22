"""Install active-request intake checklists after canonical payment/runtime wiring."""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from korgan import client_document_feedback_hotfix as core

LOGGER = logging.getLogger(__name__)
_INSTALLED = False


def _wrap_prompt(
    original: Callable[..., Awaitable[None]],
    kind: str,
) -> Callable[..., Awaitable[None]]:
    """Append one checklist after the existing prompt for the current request."""
    if getattr(original, "_korgan_client_guidance", False):
        return original

    async def guided(*args: Any, **kwargs: Any) -> None:
        await original(*args, **kwargs)
        if len(args) < 2:
            return
        try:
            await core.send_checklist_once(args[0], args[1], kind)
        except Exception:
            LOGGER.exception("CLIENT_CHECKLIST_FAILED kind=%s", kind)

    guided._korgan_client_guidance = True  # type: ignore[attr-defined]
    return guided


def install_client_document_runtime_guidance() -> None:
    """Wrap intake prompts only; generators and prepayment assignments stay intact."""
    global _INSTALLED
    if _INSTALLED:
        return

    from korgan import pretrial, pretrial_response, pretrial_response_runtime, pretrial_runtime
    from korgan import universal_claim_runtime, universal_document_runtime

    universal_claim_runtime.begin_claim_request = _wrap_prompt(
        universal_claim_runtime.begin_claim_request, "claim"
    )
    # universal_document_runtime imported this symbol by value; refresh the alias
    # so its RU claim callback cannot bypass the checklist wrapper.
    if hasattr(universal_document_runtime, "begin_claim_request"):
        universal_document_runtime.begin_claim_request = universal_claim_runtime.begin_claim_request

    pretrial_runtime._ask_pretrial = _wrap_prompt(pretrial_runtime._ask_pretrial, "pretrial")
    pretrial_response_runtime._ask_materials = _wrap_prompt(
        pretrial_response_runtime._ask_materials, "pretrial_response"
    )
    universal_document_runtime._ask_contract = _wrap_prompt(
        universal_document_runtime._ask_contract, "contract"
    )
    universal_document_runtime._ask_response = _wrap_prompt(
        universal_document_runtime._ask_response, "response"
    )

    # Runtime modules import these by value. Refresh only QA/renderer aliases;
    # generation/payment functions themselves are never replaced here.
    pretrial_runtime.pretrial_quality_issues = pretrial.pretrial_quality_issues
    pretrial_response_runtime.pretrial_response_quality_issues = pretrial_response.pretrial_response_quality_issues
    pretrial_response_runtime.build_pretrial_response_docx = pretrial_response.build_pretrial_response_docx

    _INSTALLED = True
    LOGGER.info("Installed KORGAN active-request document intake checklists")
