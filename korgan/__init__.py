"""KORGAN Legal AI."""

from korgan import claim_quality_hotfix as _claim_quality_hotfix
from korgan.claim_consistency_guard import install_claim_consistency_guard
from korgan.claim_core_release_runtime import install_claim_core_release_guard
from korgan.claim_release_repair import install_claim_release_repair
from korgan.client_document_feedback_safe import install_client_document_feedback_safe

install_claim_consistency_guard()
install_claim_release_repair()
install_client_document_feedback_safe()

# strict_bot imports install_runtime_hotfix only after package initialization.
# claim_release_repair has already replaced that installer with its production
# wrapper at this point. Layer the core claim release guard after that complete
# installed sender so no hotfix can replace/bypass the substantive gate.
_installed_claim_hotfix = _claim_quality_hotfix.install_runtime_hotfix


def _install_claim_hotfix_with_core_release_guard() -> None:
    _installed_claim_hotfix()
    install_claim_core_release_guard()


_claim_quality_hotfix.install_runtime_hotfix = _install_claim_hotfix_with_core_release_guard
