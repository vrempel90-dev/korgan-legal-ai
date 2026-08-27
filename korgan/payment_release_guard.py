from __future__ import annotations

from dataclasses import dataclass


PAID_DOCUMENT_KINDS = frozenset({"claim", "pretrial", "pretrial_response", "response", "contract"})


@dataclass(frozen=True)
class ReleaseDecision:
    allowed: bool
    reason: str


def can_release_paid_document(
    *,
    kind: str,
    receipt_submitted: bool,
    receipt_precheck_passed: bool,
    ofd_verified: bool = False,
    ai_verified: bool = False,
    admin_confirmed: bool = False,
) -> ReleaseDecision:
    """Fail closed until a trusted payment verifier has accepted the receipt.

    The production path is deterministic Kaspi OFD verification from the fiscal
    receipt QR. ``ai_verified`` and ``admin_confirmed`` remain only for already
    open legacy transactions created before the OFD verifier deployment.
    """
    if kind not in PAID_DOCUMENT_KINDS:
        return ReleaseDecision(False, "unsupported_paid_document_kind")
    if not receipt_submitted:
        return ReleaseDecision(False, "receipt_required")
    if not receipt_precheck_passed:
        return ReleaseDecision(False, "receipt_verification_required")
    if not (ofd_verified or ai_verified or admin_confirmed):
        return ReleaseDecision(False, "payment_verification_required")
    if ofd_verified:
        return ReleaseDecision(True, "payment_kaspi_ofd_verified")
    if ai_verified:
        return ReleaseDecision(True, "payment_ai_verified")
    return ReleaseDecision(True, "payment_legacy_admin_confirmed")
