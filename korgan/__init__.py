"""KORGAN Legal AI."""

from korgan import claim_quality_hotfix as _claim_quality_hotfix
from korgan import universal_word_final_hardening as _universal_word_final_hardening
from korgan.claim_consistency_guard import install_claim_consistency_guard
from korgan.claim_core_release_runtime import install_claim_core_release_guard
from korgan.claim_release_repair import install_claim_release_repair
from korgan.claim_upload_material_bridge import install_claim_upload_material_bridge
from korgan.client_document_feedback_safe import install_client_document_feedback_safe
from korgan.manual_claim_calculation_policy import install_manual_claim_calculation_policy

install_claim_consistency_guard()
install_claim_release_repair()
install_claim_upload_material_bridge()
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

# strict_bot imports the Word hardening installer after package initialization.
# Run the manual-calculation policy immediately after that hardening so all older
# state-duty/Article-353 hotfixes remain underneath one final invariant: amounts
# reach a claim only from the Mini App calculator's «Добавить в иск» line.
_installed_word_hardening = _universal_word_final_hardening.install_universal_word_final_hardening


def _install_word_hardening_with_manual_claim_calculations() -> None:
    _installed_word_hardening()
    install_manual_claim_calculation_policy()


_universal_word_final_hardening.install_universal_word_final_hardening = (
    _install_word_hardening_with_manual_claim_calculations
)
