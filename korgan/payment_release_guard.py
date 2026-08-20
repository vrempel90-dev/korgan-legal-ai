from __future__ import annotations

from dataclasses import dataclass


PAID_DOCUMENT_KINDS = frozenset({"claim", "pretrial", "response", "contract"})


@dataclass(frozen=True)
class ReleaseDecision:
    allowed: bool
    reason: str


def can_release_paid_document(
    *,
    kind: str,
    receipt_submitted: bool,
    receipt_precheck_passed: bool,
    admin_confirmed: bool,
) -> ReleaseDecision:
    """Single fail-closed rule for paid legal document delivery.

    A generated document is never equivalent to a releasable document. For every
    paid KORGAN document the client must submit a receipt, the automated receipt
    pre-check must pass, and an administrator must confirm the actual payment.
    """
    if kind not in PAID_DOCUMENT_KINDS:
        return ReleaseDecision(False, "unsupported_paid_document_kind")
    if not receipt_submitted:
        return ReleaseDecision(False, "receipt_required")
    if not receipt_precheck_passed:
        return ReleaseDecision(False, "receipt_precheck_required")
    if not admin_confirmed:
        return ReleaseDecision(False, "admin_confirmation_required")
    return ReleaseDecision(True, "payment_confirmed")
