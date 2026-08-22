"""Install document intake checklists after canonical runtime/payment wiring."""

from __future__ import annotations

import logging

from korgan import client_document_feedback_hotfix as core

LOGGER = logging.getLogger(__name__)
_INSTALLED = False


def install_client_document_runtime_guidance() -> None:
    """Wrap intake prompts only; never wrap or replace a document generator."""
    global _INSTALLED
    if _INSTALLED:
        return

    from korgan import pretrial_response, pretrial_response_runtime, pretrial_runtime
    from korgan import universal_claim_runtime, universal_document_runtime

    core._wrap_guidance(universal_claim_runtime, "begin_claim_request", "claim")
    core._wrap_guidance(pretrial_runtime, "_ask_pretrial", "pretrial")
    core._wrap_guidance(pretrial_response_runtime, "_ask_materials", "pretrial_response")
    core._wrap_guidance(universal_document_runtime, "_ask_contract", "contract")
    core._wrap_guidance(universal_document_runtime, "_ask_response", "response")

    # These runtime modules import quality/renderer functions by value. Refresh
    # the aliases only after every runtime is loaded; generators/payment wrappers
    # themselves remain untouched.
    from korgan import pretrial

    pretrial_runtime.pretrial_quality_issues = pretrial.pretrial_quality_issues
    pretrial_response_runtime.pretrial_response_quality_issues = pretrial_response.pretrial_response_quality_issues
    pretrial_response_runtime.build_pretrial_response_docx = pretrial_response.build_pretrial_response_docx

    _INSTALLED = True
    LOGGER.info("Installed KORGAN client document intake checklists")
