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
    ai_verified: bool = False,
    admin_confirmed: bool = False,
) -> ReleaseDecision:
    """Fail closed until the submitted receipt is accepted by the payment verifier.

    The normal production path is automatic: a receipt must be submitted, the
    strict receipt checks must pass, and the AI payment verifier must explicitly
    accept it. ``admin_confirmed`` remains only as a compatibility escape hatch
    for already-open legacy payment transactions from older deployments.
    """
    if kind not in PAID_DOCUMENT_KINDS:
        return ReleaseDecision(False, "unsupported_paid_document_kind")
    if not receipt_submitted:
        return ReleaseDecision(False, "receipt_required")
    if not receipt_precheck_passed:
        return ReleaseDecision(False, "receipt_verification_required")
    if not (ai_verified or admin_confirmed):
        return ReleaseDecision(False, "payment_verification_required")
    return ReleaseDecision(True, "payment_ai_verified" if ai_verified else "payment_legacy_admin_confirmed")
